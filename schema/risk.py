"""Explainable review-priority contracts; never a fraud probability or decision."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from schema.api import ClaimResponse

RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"]
ReasonCode = Literal[
    "missing_patient_name",
    "missing_provider_name",
    "missing_service_date",
    "missing_amount",
    "invalid_data",
    "unverified_extraction",
    "unverified_semantics",
    "unsupported_currency",
    "amount_medium",
    "amount_high",
    "possible_duplicate_document",
    "duplicate_context_unavailable",
]
EvidencePath = Literal[
    "patient.full_name",
    "provider.name",
    "service.service_date",
    "billing.total_amount",
    "billing.currency",
    "extraction.confidence",
    "validation",
    "document.sha256",
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PolicyVersion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class RiskContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskSignal(RiskContract):
    code: ReasonCode
    evidence_fields: list[EvidencePath] = Field(min_length=1, max_length=8)
    message: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class RiskEvaluation(RiskContract):
    level: RiskLevel
    policy_version: PolicyVersion
    signals: list[RiskSignal] = Field(max_length=16)
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    assessed_at: AwareDatetime
    context_at: AwareDatetime

    @model_validator(mode="after")
    def consistent_level(self):
        codes = [signal.code for signal in self.signals]
        if len(codes) != len(set(codes)) or codes != sorted(codes):
            raise ValueError("Signals must have unique codes in sorted order")
        insufficient = set(codes) - {"amount_medium", "amount_high", "possible_duplicate_document"}
        expected = (
            "INSUFFICIENT_DATA"
            if insufficient
            else "HIGH"
            if {"amount_high", "possible_duplicate_document"}.intersection(codes)
            else "MEDIUM"
            if "amount_medium" in codes
            else "LOW"
        )
        if self.level != expected:
            raise ValueError("Risk level must agree with signal precedence")
        if "amount_medium" in codes and "amount_high" in codes:
            raise ValueError("Amount bands are mutually exclusive")
        return self


class RiskAssessmentResponse(RiskEvaluation):
    input_fingerprint: Fingerprint = Field(exclude=True)
    context_fingerprint: Fingerprint = Field(exclude=True)
    assessment_id: UUID
    claim_id: UUID
    extraction_id: UUID
    claim_version: int = Field(ge=1)


class RiskRefreshCreate(RiskContract):
    expected_version: int = Field(ge=1, strict=True)


class RiskAcknowledgmentCreate(RiskRefreshCreate):
    assessment_id: UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class RiskAcknowledgmentResponse(RiskContract):
    acknowledgment_id: UUID
    assessment_id: UUID
    actor_id: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    created_at: AwareDatetime


class RiskHistoryResponse(RiskContract):
    items: list[RiskAssessmentResponse] = Field(max_length=100)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class RiskQueueItem(RiskContract):
    claim: ClaimResponse
    risk: RiskAssessmentResponse
    acknowledgment: RiskAcknowledgmentResponse | None


class RiskQueueResponse(RiskContract):
    items: list[RiskQueueItem] = Field(max_length=100)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
