"""Public API projections deliberately omit database/storage internals."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer


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


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
