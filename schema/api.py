"""Public API projections deliberately omit database/storage internals."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_serializer,
)


class ClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_system: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    claim_id: UUID
    state: Literal["RECEIVED", "PROCESSING", "READY", "REVIEW_REQUIRED", "FAILED", "REJECTED"] = (
        Field(validation_alias="current_state")
    )
    version: int = Field(ge=1)
    source_system: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def utc_timestamps(self, value: datetime):
        # SQLite test timestamps are naive UTC; PostgreSQL timestamps are timezone-aware.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    document_id: UUID
    claim_id: UUID
    file_name: str
    mime_type: str = Field(validation_alias="file_mime_type")
    byte_size: int = Field(gt=0)
    sha256: str
    state: Literal["UPLOADED", "QUEUED", "PROCESSING", "EXTRACTED", "FAILED"] = Field(
        validation_alias="document_state"
    )
    created_at: datetime

    @field_serializer("created_at")
    def utc_timestamp(self, value: datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]


class JobFailureResponse(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_id: UUID
    document_id: UUID
    state: Literal["QUEUED", "RUNNING", "RETRY_WAIT", "SUCCEEDED", "FAILED"]
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    next_attempt_at: datetime | None
    error_code: str | None = Field(exclude=True)
    error_message: str | None = Field(exclude=True)

    @computed_field
    @property
    def error(self) -> JobFailureResponse | None:
        if self.error_code is None:
            return None
        return JobFailureResponse(
            code=self.error_code, message=self.error_message or "Processing failed"
        )

    @field_serializer("created_at", "started_at", "completed_at", "next_attempt_at")
    def utc_job_timestamp(self, value: datetime | None):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
