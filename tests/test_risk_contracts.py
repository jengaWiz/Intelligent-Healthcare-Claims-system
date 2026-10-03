"""Strict risk contracts preserve meaning, bounds and safe public projections."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schema.risk import (
    RiskAcknowledgmentCreate,
    RiskAssessmentResponse,
    RiskEvaluation,
    RiskRefreshCreate,
)


def evaluation(**changes):
    return {
        "level": "LOW",
        "policy_version": "risk-v1",
        "signals": [],
        "input_fingerprint": "a" * 64,
        "context_fingerprint": "b" * 64,
        "assessed_at": "2026-10-03T12:00:00Z",
        "context_at": "2026-10-03T12:00:00Z",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"level": "FRAUD"},
        {"level": "HIGH"},
        {"assessed_at": "2026-10-03T12:00:00"},
        {"input_fingerprint": "not-a-hash"},
        {"probability": 0.9},
        {"signals": [{"code": "arbitrary", "message": "x", "evidence_fields": ["validation"]}]},
    ],
)
def test_reject_invalid_or_misleading_assessments(changes):
    with pytest.raises(ValidationError):
        RiskEvaluation.model_validate(evaluation(**changes))


@pytest.mark.parametrize(
    "extra", [{"level": "LOW"}, {"actor_id": "other"}, {"policy_version": "x"}]
)
def test_mutations_cannot_supply_risk_or_actor(extra):
    with pytest.raises(ValidationError):
        RiskAcknowledgmentCreate.model_validate(
            {"expected_version": 1, "assessment_id": uuid4(), "reason": "Reviewed", **extra}
        )


def test_request_limits_and_reason_normalization():
    payload = RiskAcknowledgmentCreate(
        expected_version=1, assessment_id=uuid4(), reason="  Reviewed source  "
    )
    assert payload.reason == "Reviewed source"
    for reason in (" ", "x" * 2001):
        with pytest.raises(ValidationError):
            RiskAcknowledgmentCreate(expected_version=1, assessment_id=uuid4(), reason=reason)
    for version in (0, True, "1"):
        with pytest.raises(ValidationError):
            RiskRefreshCreate(expected_version=version)


def test_public_assessment_omits_internal_fingerprints():
    assessment = RiskAssessmentResponse(
        **evaluation(),
        assessment_id=uuid4(),
        claim_id=uuid4(),
        extraction_id=uuid4(),
        claim_version=1,
    )
    public = assessment.model_dump(mode="json")
    assert "input_fingerprint" not in public
    assert "context_fingerprint" not in public
    assert public["level"] == "LOW"


def test_documented_examples_cover_all_levels():
    examples = json.loads(Path("docs/examples/risk-contracts.json").read_text())
    assessments = [RiskEvaluation.model_validate(item) for item in examples["evaluations"]]
    assert {item.level for item in assessments} == {"LOW", "MEDIUM", "HIGH", "INSUFFICIENT_DATA"}
    RiskRefreshCreate.model_validate(examples["refresh"])
    RiskAcknowledgmentCreate.model_validate(examples["acknowledgment"])
