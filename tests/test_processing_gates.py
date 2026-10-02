from datetime import date
from unittest.mock import Mock

import pytest

from agents.graphs.extraction_graph import build_extraction_graph
from agents.validation_agent import ValidationAgent
from config.settings import Settings
from services.extraction_service import run_extraction_pipeline

VALID = dict(
    patient_name="Synthetic",
    patient_dob="1980-01-01",
    provider_name="Synthetic Clinic",
    service_date="2026-10-01",
    total_amount="42.50",
    confidence=0.9,
    reasoning="Synthetic fixture is clear",
)


def process(changes=None, *, semantic='{"has_issues":false,"issues":[],"confidence":0.9}'):
    extractor = Mock()
    extractor.extract.return_value = {**VALID, **(changes or {})}
    client = Mock()
    if isinstance(semantic, Exception):
        client.invoke.side_effect = semantic
    else:
        client.invoke.return_value = semantic
    validator = ValidationAgent(client=client, today=date(2026, 10, 2))
    graph = build_extraction_graph(
        settings=Settings(_env_file=None),
        ocr=lambda path, **kwargs: {"raw_text": "Synthetic", "evidence": {"modelId": "synthetic"}},
        extractor=extractor,
        validator=validator,
    )
    return run_extraction_pipeline("synthetic.pdf", graph=graph)


def test_complete_data_ready_and_serializable():
    result = process()
    assert result.outcome == "READY"
    assert result.validation.semantic_status == "completed"
    assert result.claim_data.billing.total_amount.as_tuple().exponent == -2
    assert result.model_dump(mode="json")["claim_data"]["billing"]["total_amount"] == "42.50"
    assert result.provenance["ocr_evidence"] == {"modelId": "synthetic"}


@pytest.mark.parametrize(
    "changes",
    [
        {"patient_name": None},
        {"patient_name": " "},
        {"service_date": None},
        {"total_amount": None},
        {"total_amount": "0.00"},
        {"total_amount": "-1.00"},
        {"service_date": "2026-10-03"},
        {"patient_dob": "2026-10-01"},
        {"patient_dob": "2026-10-02"},
        {"service_date": "bad-date"},
        {"total_amount": "EUR 42.50"},
        {"patient_dob": "not-a-date"},
        {"confidence": 0.79},
        {"provider_name": None},
        {"total_amount": "150000.00"},
    ],
)
def test_uncertain_data_requires_review(changes):
    assert process(changes).outcome == "REVIEW_REQUIRED"


def test_invalid_format_issue_kept_alongside_raw_value():
    result = process({"service_date": "not-a-date"})
    assert result.extracted_data["service_date"] == "not-a-date"
    assert result.claim_data.service.service_date is None
    assert any(
        i.issue_type == "invalid" and i.field == "service.service_date"
        for i in result.validation.issues
    )


@pytest.mark.parametrize(
    "semantic",
    [
        TimeoutError("synthetic secret"),
        '{"has_issues":true,"issues":["Needs review"],"confidence":0.9}',
        '{"has_issues":false,"issues":[],"confidence":0.2}',
    ],
)
def test_semantic_failure_or_uncertainty_never_ready(semantic):
    result = process(semantic=semantic)
    assert result.outcome == "REVIEW_REQUIRED"
    assert "synthetic secret" not in result.model_dump_json()
