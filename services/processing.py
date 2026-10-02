"""Pure data-quality processing; no database work or insurance adjudication."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from config.settings import Settings
from schema.claim_data import ClaimData
from schema.validation_result import ValidationIssue, ValidationResult


class ProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extracted_data: dict
    claim_data: ClaimData
    validation: ValidationResult
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reasoning: str
    outcome: Literal["READY", "REVIEW_REQUIRED"]
    provenance: dict


def normalize_and_validate(extracted, *, validator, settings: Settings):
    claim = ClaimData.from_extracted_data(extracted)
    issues = []
    fields = [
        ("patient_dob", "patient.date_of_birth", claim.patient.date_of_birth),
        ("service_date", "service.service_date", claim.service.service_date),
        ("total_amount", "billing.total_amount", claim.billing.total_amount),
    ]
    for raw_field, path, normalized in fields:
        if extracted.get(raw_field) is not None and normalized is None:
            issues.append(
                ValidationIssue(
                    severity="critical",
                    field=path,
                    issue_type="invalid",
                    description="Extracted field could not be normalized",
                    suggested_fix="Correct the value against the source document",
                )
            )
    validation = validator.validate(claim, initial_issues=issues)
    ready = (
        claim.extraction_confidence is not None
        and claim.extraction_confidence >= settings.extraction_confidence_threshold
        and validation.is_valid
        and not validation.issues
        and validation.semantic_status == "completed"
    )
    return claim, validation, "READY" if ready else "REVIEW_REQUIRED"
