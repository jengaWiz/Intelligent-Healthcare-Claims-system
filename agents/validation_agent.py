"""
Validation Agent - Validates ClaimData for completeness, consistency, and quality.

Combines rule-based validation with LLM-powered semantic checks.
"""

import json
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import List

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat

from agents.extraction_agent import unique_fields
from config.settings import Settings, get_settings
from schema.claim_data import ClaimData
from schema.validation_result import ValidationIssue, ValidationResult
from services.provider_errors import FailureCode, ProviderFailure, classify_failure


class SemanticValidationOutput(BaseModel):
    """Output from LLM semantic validation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    has_issues: StrictBool
    issues: List[str] = Field(max_length=20)
    confidence: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)


class ValidationAgent:
    """
    Agent that validates ClaimData for quality and consistency.

    Performs both rule-based and LLM-powered validation checks.
    """

    def __init__(
        self,
        provider: str | None = None,
        model_name: str | None = None,
        settings: Settings | None = None,
        client=None,
        today: date | None = None,
    ):
        self.settings = settings or get_settings()
        self.provider = provider or self.settings.llm_provider
        self.model_name = model_name
        self._client = client
        self.today = today
        if self.provider not in {"google", "openai"}:
            raise ValueError(f"Unsupported provider: {self.provider}")
        self.parser = PydanticOutputParser(pydantic_object=SemanticValidationOutput)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a healthcare claims validation expert. Review the claim data for semantic inconsistencies.\n\n"
                    "Check for:\n"
                    "- Age-inappropriate services (e.g., pediatric care for elderly)\n"
                    "- Unusual provider-service combinations\n"
                    "- Suspicious patterns or anomalies\n"
                    "- Cross-field inconsistencies\n\n"
                    "{format_instructions}",
                ),
                ("user", "Claim Data:\n{claim_data}"),
            ]
        )

    @cached_property
    def llm(self):
        if self._client is not None:
            return self._client
        model, key = self.settings.require_llm(self.provider, self.model_name)
        options = {
            "model": model,
            "temperature": 0,
            "api_key": key,
            "timeout": self.settings.provider_timeout_seconds,
            "max_retries": 0,
            "max_tokens": 2048,
        }
        if self.provider == "openai":
            return ChatOpenAI(**options)
        return ChatGoogleGenerativeAI(**options)

    def validate(
        self, claim_data: ClaimData, *, run_semantic=True, initial_issues=()
    ) -> ValidationResult:
        """
        Validate claim data using both rule-based and LLM checks.

        Args:
            claim_data: ClaimData instance to validate

        Returns:
            ValidationResult with issues and recommendations
        """
        issues: List[ValidationIssue] = list(initial_issues)

        # Rule-based validation
        issues.extend(self._check_missing_fields(claim_data))
        issues.extend(self._check_date_logic(claim_data))
        issues.extend(self._check_amounts(claim_data))

        semantic_status = "unavailable"
        try:
            if run_semantic:
                issues.extend(self._check_semantic_consistency(claim_data))
                semantic_status = "completed"
            else:
                raise ProviderFailure("validation", FailureCode.CONFIGURATION)
        except ProviderFailure:
            issues.append(
                ValidationIssue(
                    severity="info",
                    field="semantic",
                    issue_type="suspicious",
                    description="Semantic validation is unavailable",
                    suggested_fix="Explicit human review is required",
                )
            )

        # Calculate validation score
        validation_score = self._calculate_score(issues)

        # Determine if valid (no critical issues)
        is_valid = not any(issue.severity == "critical" for issue in issues)

        # Generate recommendations
        recommendations = self._generate_recommendations(issues)

        return ValidationResult(
            semantic_status=semantic_status,
            is_valid=is_valid,
            validation_score=validation_score,
            issues=issues,
            recommendations=recommendations,
        )

    def _check_missing_fields(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Check for missing required fields."""
        issues = []

        # Required fields
        if not claim_data.patient.full_name:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="patient.full_name",
                    issue_type="missing",
                    description="Patient name is required but missing",
                    suggested_fix="Obtain patient name from source document or request from submitter",
                )
            )

        if not claim_data.service.service_date:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="service.service_date",
                    issue_type="missing",
                    description="Service date is required but missing",
                    suggested_fix="Verify service date from medical records",
                )
            )

        if claim_data.billing.total_amount is None:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="billing.total_amount",
                    issue_type="missing",
                    description="Total amount is required but missing",
                    suggested_fix="Calculate total from line items or obtain from billing statement",
                )
            )

        # Important but not critical fields
        if not claim_data.provider.name:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="provider.name",
                    issue_type="missing",
                    description="Provider name is missing",
                    suggested_fix="Identify provider from NPI or facility records",
                )
            )

        if not claim_data.patient.date_of_birth:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="patient.date_of_birth",
                    issue_type="missing",
                    description="Patient date of birth is missing",
                    suggested_fix="Request DOB for age verification and eligibility checks",
                )
            )

        return issues

    def _check_date_logic(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Validate date logic and consistency."""
        issues = []
        today = self.today or date.today()

        # Service date should not be in the future
        if claim_data.service.service_date and claim_data.service.service_date > today:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field="service.service_date",
                    issue_type="invalid",
                    description=f"Service date {claim_data.service.service_date} is in the future",
                    suggested_fix="Verify service date is correct",
                )
            )

        # DOB should be before service date
        if claim_data.patient.date_of_birth and claim_data.service.service_date:
            if claim_data.patient.date_of_birth >= claim_data.service.service_date:
                issues.append(
                    ValidationIssue(
                        severity="critical",
                        field="patient.date_of_birth",
                        issue_type="inconsistent",
                        description="Patient date of birth is after or same as service date",
                        suggested_fix="Verify patient DOB and service date",
                    )
                )

        # Check for unreasonably old service dates (> 2 years)
        if claim_data.service.service_date:
            days_old = (today - claim_data.service.service_date).days
            if days_old > 730:  # 2 years
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        field="service.service_date",
                        issue_type="suspicious",
                        description=f"Service date is {days_old} days old (over 2 years)",
                        suggested_fix="Verify this is not a duplicate or delayed submission",
                    )
                )

        return issues

    def _check_amounts(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Validate billing amounts."""
        issues = []

        if claim_data.billing.total_amount is not None:
            amount = claim_data.billing.total_amount

            # Amount should be positive
            if amount <= 0:
                issues.append(
                    ValidationIssue(
                        severity="critical",
                        field="billing.total_amount",
                        issue_type="invalid",
                        description=f"Total amount ${amount} must be positive",
                        suggested_fix="Verify billing amount from source document",
                    )
                )

            # Check for unreasonably high amounts (> $100,000)
            if amount > Decimal("100000"):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        field="billing.total_amount",
                        issue_type="suspicious",
                        description=f"Total amount ${amount} is unusually high",
                        suggested_fix="Verify amount is correct and not a data entry error",
                    )
                )

            # Check for suspiciously low amounts (< $1)
            if amount < Decimal("1"):
                issues.append(
                    ValidationIssue(
                        severity="info",
                        field="billing.total_amount",
                        issue_type="suspicious",
                        description=f"Total amount ${amount} is unusually low",
                        suggested_fix="Confirm this is the correct amount",
                    )
                )

        return issues

    def close(self):
        llm = self.__dict__.pop("llm", None)
        if llm is not None and self._client is None:
            failure = None
            try:
                (llm.root_client if self.provider == "openai" else llm.client).close()
            except Exception as exc:
                failure = classify_failure(exc, "validation")
            if failure is not None:
                raise failure

    def _check_semantic_consistency(self, claim_data: ClaimData) -> List[ValidationIssue]:
        failure = None
        try:
            prompt = self.prompt.invoke(
                {
                    "claim_data": claim_data.model_dump_json(),
                    "format_instructions": self.parser.get_format_instructions(),
                }
            )
            response = self.llm.invoke(prompt)
        except Exception as exc:
            failure = classify_failure(exc, "validation")
        if failure is not None:
            raise failure
        try:
            content = response if isinstance(response, str) else response.text
            if not isinstance(content, str) or len(content) > 32768:
                raise ValueError("Invalid semantic response")
            result = SemanticValidationOutput.model_validate(
                json.loads(content, object_pairs_hook=unique_fields)
            )
            if result.has_issues != bool(result.issues):
                raise ValueError("Inconsistent semantic response")
            if any(not issue.strip() or len(issue) > 2000 for issue in result.issues):
                raise ValueError("Invalid semantic issue")
        except (ValueError, TypeError, AttributeError, RecursionError):
            failure = ProviderFailure("validation", FailureCode.INVALID_RESPONSE)
        if failure is not None:
            raise failure
        issues = [
            ValidationIssue(
                severity="warning",
                field="semantic",
                issue_type="inconsistent",
                description=description,
                suggested_fix="Review data against source document",
            )
            for description in result.issues
        ]
        if result.confidence < self.settings.extraction_confidence_threshold:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    field="semantic",
                    issue_type="suspicious",
                    description="Semantic check confidence is below the review threshold",
                    suggested_fix="Explicit human review is required",
                )
            )
        return issues

    def _calculate_score(self, issues: List[ValidationIssue]) -> float:
        """Calculate validation score based on issues."""
        if not issues:
            return 1.0

        # Weight issues by severity
        penalty = 0.0
        for issue in issues:
            if issue.severity == "critical":
                penalty += 0.3
            elif issue.severity == "warning":
                penalty += 0.1
            else:  # info
                penalty += 0.05

        # Score is 1.0 minus penalties, clamped to [0, 1]
        score = max(0.0, 1.0 - penalty)
        return round(score, 2)

    def _generate_recommendations(self, issues: List[ValidationIssue]) -> List[str]:
        """Generate high-level recommendations based on issues."""
        recommendations = []

        critical_count = sum(1 for i in issues if i.severity == "critical")
        warning_count = sum(1 for i in issues if i.severity == "warning")

        if critical_count > 0:
            recommendations.append(
                f"Address {critical_count} critical issue(s) before processing claim"
            )

        if warning_count > 0:
            recommendations.append(f"Review {warning_count} warning(s) to improve data quality")

        # Check for missing data pattern
        missing_issues = [i for i in issues if i.issue_type == "missing"]
        if len(missing_issues) >= 3:
            recommendations.append(
                "Multiple fields are missing - consider requesting additional documentation"
            )

        # Check for date issues
        date_issues = [i for i in issues if "date" in i.field.lower()]
        if date_issues:
            recommendations.append("Verify all dates with source documents")

        if any(i.field == "semantic" for i in issues):
            recommendations.append("Review semantic findings and availability")
        if not recommendations:
            recommendations.append("Claim data quality is good")

        return recommendations
