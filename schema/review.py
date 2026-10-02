"""Bounded human corrections; only document fields are editable."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from schema.api import ClaimResponse, JobResponse
from schema.claim_data import ClaimData
from schema.validation_result import ValidationResult

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Corrections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_name: Text
    patient_dob: date | None = None
    provider_name: Text | None = None
    service_date: date
    total_amount: Decimal = Field(gt=0, le=Decimal("1000000000"), max_digits=12, decimal_places=2)

    def apply(self, original: dict) -> ClaimData:
        data = ClaimData.model_validate(original)
        data.patient.full_name = self.patient_name
        data.patient.date_of_birth = self.patient_dob
        data.provider.name = self.provider_name
        data.service.service_date = self.service_date
        data.billing.total_amount = self.total_amount
        return data


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "correct", "reject"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    corrections: Corrections | None = None

    @model_validator(mode="after")
    def correction_required(self):
        if (self.decision == "correct") != (self.corrections is not None):
            raise ValueError("Only correction decisions must include corrected fields")
        return self


class Snapshot(BaseModel):
    data: ClaimData
    validation: ValidationResult
    human_reviewed: bool = False


class AuditResponse(BaseModel):
    review_id: UUID
    actor_id: str
    decision: Literal["approve", "correct", "reject"]
    reason: str
    previous_version: int
    new_version: int
    before_data: Snapshot
    after_data: Snapshot
    created_at: datetime


class ExtractionResponse(BaseModel):
    extraction_id: UUID
    engine: str
    version: str
    original_data: ClaimData
    confidence: float
    reasoning: str | None
    outcome: Literal["READY", "REVIEW_REQUIRED"]
    provenance: dict
    created_at: datetime


class ResultsResponse(BaseModel):
    claim: ClaimResponse
    job: JobResponse | None
    extraction: ExtractionResponse | None
    current: Snapshot | None
    reviews: list[AuditResponse]
