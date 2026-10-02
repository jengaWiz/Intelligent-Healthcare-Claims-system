from datetime import date
from unittest.mock import Mock

import pytest

from agents.validation_agent import ValidationAgent
from schema.claim_data import ClaimData


def claim(amount="0.00"):
    return ClaimData.from_extracted_data(
        dict(
            patient_name="Synthetic",
            patient_dob="1980-01-01",
            provider_name="Synthetic Clinic",
            service_date="2026-10-01",
            total_amount=amount,
        )
    )


def test_zero_is_invalid_not_missing():
    result = ValidationAgent(today=date(2026, 10, 2)).validate(claim(), run_semantic=False)
    amount_issues = [i for i in result.issues if i.field == "billing.total_amount"]
    assert any(i.issue_type == "invalid" and i.severity == "critical" for i in amount_issues)
    assert all(i.issue_type != "missing" for i in amount_issues)
    assert result.semantic_status == "unavailable"


@pytest.mark.parametrize(
    "output",
    [
        '{"has_issues":false,"issues":[],"confidence":0.9',
        '{"has_issues":false,"issues":["Contradiction"],"confidence":0.9}',
        '{"has_issues":false,"issues":[],"confidence":2}',
    ],
)
def test_invalid_semantic_output_requires_review(output):
    client = Mock()
    client.invoke.return_value = output
    result = ValidationAgent(client=client, today=date(2026, 10, 2)).validate(claim("42.50"))
    assert result.semantic_status == "unavailable"
    assert any(i.field == "semantic" for i in result.issues)


def test_semantic_failure_does_not_echo_error_or_recommend_clean_data():
    client = Mock()
    client.invoke.side_effect = TimeoutError("synthetic secret and document text")
    result = ValidationAgent(client=client, today=date(2026, 10, 2)).validate(claim("42.50"))
    assert "synthetic secret" not in result.model_dump_json()
    assert result.semantic_status == "unavailable"
    assert "Claim data quality is good" not in result.recommendations


def test_valid_semantic_output_completes():
    client = Mock()
    client.invoke.return_value = '{"has_issues":false,"issues":[],"confidence":0.9}'
    result = ValidationAgent(client=client, today=date(2026, 10, 2)).validate(claim("42.50"))
    assert result.semantic_status == "completed" and not result.issues
