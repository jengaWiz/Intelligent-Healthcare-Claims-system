"""
Validation Result Schema - Structured output from validation agent.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ValidationIssue(BaseModel):
    """Represents a single validation issue found in claim data."""

    severity: Literal["critical", "warning", "info"] = Field(
        description="Severity level of the issue"
    )
    field: str = Field(
        description="Field path where the issue was found (e.g., 'patient.date_of_birth')"
    )
    issue_type: Literal["missing", "inconsistent", "invalid", "suspicious"] = Field(
        description="Type of validation issue"
    )
    description: str = Field(description="Human-readable description of the issue")
    suggested_fix: Optional[str] = Field(
        None, description="Suggested fix or action to resolve the issue"
    )


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_status: Literal["completed", "unavailable"] = "unavailable"
    """
    Result of validating a ClaimData instance.

    Contains overall validation status, score, and detailed issues.
    """

    is_valid: bool = Field(description="Whether the claim data passes all critical validations")
    validation_score: float = Field(
        description="Overall validation score from 0.0 (many issues) to 1.0 (perfect)",
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
    )
    issues: List[ValidationIssue] = Field(
        default_factory=list, description="List of validation issues found"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="High-level recommendations for improving data quality"
    )

    @property
    def critical_issues(self) -> List[ValidationIssue]:
        """Get only critical issues."""
        return [issue for issue in self.issues if issue.severity == "critical"]

    @property
    def warning_issues(self) -> List[ValidationIssue]:
        """Get only warning issues."""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def has_critical_issues(self) -> bool:
        """Check if there are any critical issues."""
        return len(self.critical_issues) > 0
