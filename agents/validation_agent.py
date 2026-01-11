"""
Validation Agent - Validates ClaimData for completeness, consistency, and quality.

Combines rule-based validation with LLM-powered semantic checks.
"""

from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from schema.claim_data import ClaimData
from schema.validation_result import ValidationResult, ValidationIssue


class SemanticValidationOutput(BaseModel):
    """Output from LLM semantic validation."""
    has_issues: bool = Field(description="Whether semantic issues were found")
    issues: List[str] = Field(default_factory=list, description="List of semantic issues")
    confidence: float = Field(description="Confidence in the validation (0.0 to 1.0)")


class ValidationAgent:
    """
    Agent that validates ClaimData for quality and consistency.
    
    Performs both rule-based and LLM-powered validation checks.
    """
    
    def __init__(self, provider: str = "google", model_name: str = "gemini-1.5-pro"):
        """Initialize validation agent with LLM for semantic checks."""
        self.llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)
        self.parser = PydanticOutputParser(pydantic_object=SemanticValidationOutput)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are a healthcare claims validation expert. Review the claim data for semantic inconsistencies.\n\n"
             "Check for:\n"
             "- Age-inappropriate services (e.g., pediatric care for elderly)\n"
             "- Unusual provider-service combinations\n"
             "- Suspicious patterns or anomalies\n"
             "- Cross-field inconsistencies\n\n"
             "{format_instructions}"),
            ("user", "Claim Data:\n{claim_data}")
        ])
    
    def validate(self, claim_data: ClaimData) -> ValidationResult:
        """
        Validate claim data using both rule-based and LLM checks.
        
        Args:
            claim_data: ClaimData instance to validate
            
        Returns:
            ValidationResult with issues and recommendations
        """
        issues: List[ValidationIssue] = []
        
        # Rule-based validation
        issues.extend(self._check_missing_fields(claim_data))
        issues.extend(self._check_date_logic(claim_data))
        issues.extend(self._check_amounts(claim_data))
        
        # LLM-powered semantic validation
        semantic_issues = self._check_semantic_consistency(claim_data)
        issues.extend(semantic_issues)
        
        # Calculate validation score
        validation_score = self._calculate_score(issues)
        
        # Determine if valid (no critical issues)
        is_valid = not any(issue.severity == "critical" for issue in issues)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(issues)
        
        return ValidationResult(
            is_valid=is_valid,
            validation_score=validation_score,
            issues=issues,
            recommendations=recommendations
        )
    
    def _check_missing_fields(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Check for missing required fields."""
        issues = []
        
        # Required fields
        if not claim_data.patient.full_name:
            issues.append(ValidationIssue(
                severity="critical",
                field="patient.full_name",
                issue_type="missing",
                description="Patient name is required but missing",
                suggested_fix="Obtain patient name from source document or request from submitter"
            ))
        
        if not claim_data.service.service_date:
            issues.append(ValidationIssue(
                severity="critical",
                field="service.service_date",
                issue_type="missing",
                description="Service date is required but missing",
                suggested_fix="Verify service date from medical records"
            ))
        
        if not claim_data.billing.total_amount:
            issues.append(ValidationIssue(
                severity="critical",
                field="billing.total_amount",
                issue_type="missing",
                description="Total amount is required but missing",
                suggested_fix="Calculate total from line items or obtain from billing statement"
            ))
        
        # Important but not critical fields
        if not claim_data.provider.name:
            issues.append(ValidationIssue(
                severity="warning",
                field="provider.name",
                issue_type="missing",
                description="Provider name is missing",
                suggested_fix="Identify provider from NPI or facility records"
            ))
        
        if not claim_data.patient.date_of_birth:
            issues.append(ValidationIssue(
                severity="warning",
                field="patient.date_of_birth",
                issue_type="missing",
                description="Patient date of birth is missing",
                suggested_fix="Request DOB for age verification and eligibility checks"
            ))
        
        return issues
    
    def _check_date_logic(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Validate date logic and consistency."""
        issues = []
        today = date.today()
        
        # Service date should not be in the future
        if claim_data.service.service_date and claim_data.service.service_date > today:
            issues.append(ValidationIssue(
                severity="critical",
                field="service.service_date",
                issue_type="invalid",
                description=f"Service date {claim_data.service.service_date} is in the future",
                suggested_fix="Verify service date is correct"
            ))
        
        # DOB should be before service date
        if claim_data.patient.date_of_birth and claim_data.service.service_date:
            if claim_data.patient.date_of_birth >= claim_data.service.service_date:
                issues.append(ValidationIssue(
                    severity="critical",
                    field="patient.date_of_birth",
                    issue_type="inconsistent",
                    description="Patient date of birth is after or same as service date",
                    suggested_fix="Verify patient DOB and service date"
                ))
        
        # Check for unreasonably old service dates (> 2 years)
        if claim_data.service.service_date:
            days_old = (today - claim_data.service.service_date).days
            if days_old > 730:  # 2 years
                issues.append(ValidationIssue(
                    severity="warning",
                    field="service.service_date",
                    issue_type="suspicious",
                    description=f"Service date is {days_old} days old (over 2 years)",
                    suggested_fix="Verify this is not a duplicate or delayed submission"
                ))
        
        return issues
    
    def _check_amounts(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Validate billing amounts."""
        issues = []
        
        if claim_data.billing.total_amount:
            amount = claim_data.billing.total_amount
            
            # Amount should be positive
            if amount <= 0:
                issues.append(ValidationIssue(
                    severity="critical",
                    field="billing.total_amount",
                    issue_type="invalid",
                    description=f"Total amount ${amount} must be positive",
                    suggested_fix="Verify billing amount from source document"
                ))
            
            # Check for unreasonably high amounts (> $100,000)
            if amount > Decimal("100000"):
                issues.append(ValidationIssue(
                    severity="warning",
                    field="billing.total_amount",
                    issue_type="suspicious",
                    description=f"Total amount ${amount} is unusually high",
                    suggested_fix="Verify amount is correct and not a data entry error"
                ))
            
            # Check for suspiciously low amounts (< $1)
            if amount < Decimal("1"):
                issues.append(ValidationIssue(
                    severity="info",
                    field="billing.total_amount",
                    issue_type="suspicious",
                    description=f"Total amount ${amount} is unusually low",
                    suggested_fix="Confirm this is the correct amount"
                ))
        
        return issues
    
    def _check_semantic_consistency(self, claim_data: ClaimData) -> List[ValidationIssue]:
        """Use LLM to check semantic consistency."""
        issues = []
        
        try:
            # Prepare claim data summary for LLM
            claim_summary = f"""
Patient: {claim_data.patient.full_name or 'Unknown'}
Date of Birth: {claim_data.patient.date_of_birth or 'Unknown'}
Provider: {claim_data.provider.name or 'Unknown'}
Service Date: {claim_data.service.service_date or 'Unknown'}
Amount: ${claim_data.billing.total_amount or 'Unknown'}
"""
            
            chain = self.prompt | self.llm | self.parser
            result = chain.invoke({
                "claim_data": claim_summary,
                "format_instructions": self.parser.get_format_instructions()
            })
            
            # Convert LLM issues to ValidationIssue objects
            if result.has_issues:
                for issue_desc in result.issues:
                    issues.append(ValidationIssue(
                        severity="warning",
                        field="semantic",
                        issue_type="inconsistent",
                        description=issue_desc,
                        suggested_fix="Review claim for accuracy"
                    ))
        except Exception as e:
            # If LLM validation fails, add an info issue but don't fail validation
            issues.append(ValidationIssue(
                severity="info",
                field="semantic",
                issue_type="suspicious",
                description=f"Semantic validation could not be completed: {str(e)}",
                suggested_fix="Manual review recommended"
            ))
        
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
            recommendations.append(
                f"Review {warning_count} warning(s) to improve data quality"
            )
        
        # Check for missing data pattern
        missing_issues = [i for i in issues if i.issue_type == "missing"]
        if len(missing_issues) >= 3:
            recommendations.append(
                "Multiple fields are missing - consider requesting additional documentation"
            )
        
        # Check for date issues
        date_issues = [i for i in issues if "date" in i.field.lower()]
        if date_issues:
            recommendations.append(
                "Verify all dates with source documents"
            )
        
        if not recommendations:
            recommendations.append("Claim data quality is good")
        
        return recommendations
