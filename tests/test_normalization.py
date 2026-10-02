from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from schema.claim_data import BillingInfo, ClaimData, PatientInfo, ServiceInfo


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("USD 1,234.5600", "1234.5600"),
        ("$0.00", "0.00"),
        ("-42.50", "-42.50"),
        ("9007199254740993.01", "9007199254740993.01"),
    ],
)
def test_exact_currency_normalization(raw, expected):
    billing = BillingInfo(total_amount=raw, currency=" usd ")
    assert billing.total_amount == Decimal(expected)
    assert billing.model_dump(mode="json")["total_amount"] == expected
    assert billing.currency == "USD"


@pytest.mark.parametrize("raw", ["EUR 42.50", "12,34", "NaN", "Infinity", float("inf"), True])
def test_invalid_amount_stays_missing_for_review(raw):
    assert BillingInfo(total_amount=raw).total_amount is None


def test_unsupported_currency_rejected():
    with pytest.raises(ValidationError):
        BillingInfo(currency="EUR")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2025-01-15", date(2025, 1, 15)),
        ("01/15/2025", date(2025, 1, 15)),
        ("15/01/2025", date(2025, 1, 15)),
        ("02/30/2025", None),
    ],
)
def test_date_normalization(raw, expected):
    assert ServiceInfo(service_date=raw).service_date == expected


def test_canonical_json_roundtrip_keeps_dates_and_exact_zero():
    claim = ClaimData(
        patient=PatientInfo(full_name="  Synthetic  ", date_of_birth="1980-01-15"),
        billing=BillingInfo(total_amount="0.00"),
    )
    restored = ClaimData.model_validate_json(claim.model_dump_json())
    assert restored == claim
    assert claim.patient.full_name == "Synthetic"
    assert claim.model_dump(mode="json")["billing"]["total_amount"] == "0.00"


def test_llm_numeric_amount_is_parsed_without_binary_float_loss():
    from unittest.mock import Mock

    from agents.extraction_agent import ExtractionAgent

    client = Mock()
    client.invoke.return_value = (
        '{"patient_name":null,"patient_dob":null,"provider_name":null,'
        '"service_date":null,"total_amount":9007199254740993.01,"confidence":0.9,'
        '"reasoning":"Synthetic precision fixture"}'
    )
    result = ExtractionAgent(client=client).extract("Synthetic")
    assert result["total_amount"] == "9007199254740993.01"
    assert ClaimData.from_extracted_data(result).billing.total_amount == Decimal(
        "9007199254740993.01"
    )
