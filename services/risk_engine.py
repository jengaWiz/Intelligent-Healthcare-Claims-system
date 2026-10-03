"""Pure, deterministic review priority from explicit data and scoped context."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from schema.claim_data import ClaimData
from schema.risk import Fingerprint, PolicyVersion, RiskContract, RiskEvaluation, RiskSignal
from schema.validation_result import ValidationResult


class RiskPolicy(RiskContract):
    version: PolicyVersion
    currency: Literal["USD"]
    medium_amount: Decimal = Field(gt=0, allow_inf_nan=False)
    high_amount: Decimal = Field(gt=0, allow_inf_nan=False)
    confidence_threshold: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_bands(self):
        if self.medium_amount >= self.high_amount:
            raise ValueError("Medium threshold must be below high threshold")
        return self


class RiskContext(RiskContract):
    """Caller supplies an ownership-scoped committed snapshot, never browser data."""

    duplicate_count: int = Field(ge=0, strict=True)
    fingerprint: Fingerprint
    captured_at: AwareDatetime


@lru_cache(maxsize=1)
def load_policy() -> RiskPolicy:
    path = Path(__file__).resolve().parents[1] / "config" / "risk-v1.json"
    return RiskPolicy.model_validate_json(path.read_text())


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def assess(
    data: ClaimData,
    validation: ValidationResult,
    *,
    human_verified: bool,
    context: RiskContext,
    assessed_at: datetime,
    policy: RiskPolicy,
) -> RiskEvaluation:
    """No database, clock, network or LLM access; all inputs are explicit."""
    signals = []

    def signal(code, fields, message):
        signals.append(RiskSignal(code=code, evidence_fields=fields, message=message))

    required = [
        (data.patient.full_name, "missing_patient_name", "patient.full_name"),
        (data.provider.name, "missing_provider_name", "provider.name"),
        (data.service.service_date, "missing_service_date", "service.service_date"),
        (data.billing.total_amount, "missing_amount", "billing.total_amount"),
    ]
    for value, code, path in required:
        if value is None or isinstance(value, str) and not value.strip():
            signal(code, [path], "Required evidence is missing for review-priority assessment.")

    amount = data.billing.total_amount
    if (
        not validation.is_valid
        or validation.has_critical_issues
        or amount is not None
        and amount <= 0
    ):
        signal(
            "invalid_data", ["validation"], "Resolve invalid data before assessing review priority."
        )
    if not human_verified:
        confidence = data.extraction_confidence
        if confidence is None or confidence < policy.confidence_threshold:
            signal(
                "unverified_extraction",
                ["extraction.confidence"],
                "Extraction evidence needs human verification.",
            )
        if validation.semantic_status != "completed":
            signal(
                "unverified_semantics",
                ["validation"],
                "Semantic evidence needs human verification.",
            )
    if data.billing.currency != policy.currency:
        signal(
            "unsupported_currency",
            ["billing.currency"],
            "No review-priority amount policy exists for this currency.",
        )
    elif amount is not None:
        if amount > policy.high_amount:
            signal(
                "amount_high",
                ["billing.total_amount"],
                "Amount exceeds the illustrative high review threshold.",
            )
        elif amount > policy.medium_amount:
            signal(
                "amount_medium",
                ["billing.total_amount"],
                "Amount exceeds the illustrative medium review threshold.",
            )
    if context.duplicate_count:
        signal(
            "possible_duplicate_document",
            ["document.sha256"],
            "An eligible same-workspace document has identical bytes.",
        )

    signals.sort(key=lambda item: item.code)
    codes = {item.code for item in signals}
    insufficient = codes - {"amount_medium", "amount_high", "possible_duplicate_document"}
    level = (
        "INSUFFICIENT_DATA"
        if insufficient
        else "HIGH"
        if codes.intersection({"amount_high", "possible_duplicate_document"})
        else "MEDIUM"
        if "amount_medium" in codes
        else "LOW"
    )
    # Operational hashes stay internal; public signals contain no patient values.
    inputs = {
        "data": data.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "human_verified": human_verified,
        "policy": policy.model_dump(mode="json"),
    }
    return RiskEvaluation(
        level=level,
        policy_version=policy.version,
        signals=signals,
        input_fingerprint=fingerprint(inputs),
        context_fingerprint=context.fingerprint,
        assessed_at=assessed_at.astimezone(UTC) if assessed_at.tzinfo else assessed_at,
        context_at=context.captured_at.astimezone(UTC),
    )
