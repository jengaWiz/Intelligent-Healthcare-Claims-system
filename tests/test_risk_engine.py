"""Policy boundaries and incomplete evidence are decision-relevant, not probabilities."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from schema.claim_data import ClaimData
from schema.validation_result import ValidationIssue, ValidationResult
from services.risk_engine import RiskContext, RiskPolicy, assess, load_policy

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def run(
    *,
    amount="42.50",
    currency="USD",
    confidence=0.95,
    human=False,
    duplicates=0,
    semantic="completed",
    valid=True,
    missing=None,
    issues=(),
):
    data = ClaimData.from_extracted_data(
        {
            "patient_name": "Synthetic Patient",
            "provider_name": "Synthetic Provider",
            "service_date": "2026-10-01",
            "total_amount": amount,
            "confidence": confidence,
        }
    )
    data.billing.currency = currency
    if missing:
        section, field = missing.split(".")
        setattr(getattr(data, section), field, None)
    validation = ValidationResult(
        is_valid=valid, validation_score=1, semantic_status=semantic, issues=list(issues)
    )
    context = RiskContext(duplicate_count=duplicates, fingerprint="b" * 64, captured_at=NOW)
    return assess(
        data,
        validation,
        human_verified=human,
        context=context,
        assessed_at=NOW,
        policy=load_policy(),
    )


@pytest.mark.parametrize(
    "amount,level",
    [
        ("0.01", "LOW"),
        ("10000", "LOW"),
        ("10000.01", "MEDIUM"),
        ("100000", "MEDIUM"),
        ("100000.01", "HIGH"),
        ("0", "INSUFFICIENT_DATA"),
        ("-1", "INSUFFICIENT_DATA"),
    ],
)
def test_exact_amount_boundaries(amount, level):
    assert run(amount=amount).level == level


@pytest.mark.parametrize(
    "missing",
    ["patient.full_name", "provider.name", "service.service_date", "billing.total_amount"],
)
def test_missing_evidence_preserves_known_duplicate_signal(missing):
    result = run(missing=missing, duplicates=1)
    assert result.level == "INSUFFICIENT_DATA"
    assert "possible_duplicate_document" in {item.code for item in result.signals}


def test_human_verification_does_not_waive_substantive_signals():
    result = run(amount="100001", confidence=0.1, semantic="unavailable", human=True, duplicates=1)
    assert result.level == "HIGH"
    assert [item.code for item in result.signals] == ["amount_high", "possible_duplicate_document"]
    assert run(human=True, missing="provider.name").level == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("confidence", [None, 0.0, 0.799999])
def test_unverified_extraction(confidence):
    assert run(confidence=confidence).level == "INSUFFICIENT_DATA"


def test_confidence_equality_and_unavailable_semantics():
    assert run(confidence=0.8).level == "LOW"
    assert run(semantic="unavailable").level == "INSUFFICIENT_DATA"


def test_unsupported_currency_does_not_apply_usd_amount_rules():
    result = run(amount="100001", currency="EUR")
    assert result.level == "INSUFFICIENT_DATA"
    assert [item.code for item in result.signals] == ["unsupported_currency"]


def test_critical_validation_even_if_inconsistent_is_valid_flag():
    issue = ValidationIssue(
        severity="critical",
        field="service.service_date",
        issue_type="invalid",
        description="Invalid",
    )
    assert run(issues=[issue]).level == "INSUFFICIENT_DATA"
    assert run(valid=False).level == "INSUFFICIENT_DATA"


def test_deterministic_signals_and_no_patient_values_in_evidence():
    first = run(amount="100001", confidence=None, duplicates=2)
    assert first == run(amount="100001", confidence=None, duplicates=2)
    assert "Synthetic Patient" not in str(first.signals)
    assert (
        first.input_fingerprint
        != run(amount="100002", confidence=None, duplicates=2).input_fingerprint
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"medium_amount": "100000"},
        {"high_amount": "9999"},
        {"medium_amount": "NaN"},
        {"confidence_threshold": 1.1},
        {"currency": "EUR"},
        {"weight": 1},
    ],
)
def test_invalid_policy_fails_closed(changes):
    with pytest.raises(ValidationError):
        RiskPolicy.model_validate({**load_policy().model_dump(), **changes})
