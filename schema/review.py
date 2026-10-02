"""Bounded human corrections; only document fields are editable."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from schema.claim_data import ClaimData

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
