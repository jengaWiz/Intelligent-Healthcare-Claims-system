"""Synthetic scenario expectations are rule conformance, never fraud accuracy."""

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pytest

import agents.validation_agent as validation_module
from config.settings import Settings
from services.risk_engine import RiskContext, assess, load_policy
from services.synthetic_processor import process_sample

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "samples/manifest.json").read_text())
NOW = datetime(2026, 10, 3, tzinfo=UTC)


@pytest.mark.parametrize("scenario", ["valid", "medium", "high", "review", "duplicate"])
def test_versioned_risk_scenarios_match_rule_policy(scenario):
    entry = MANIFEST["scenarios"][scenario]
    path = ROOT / "samples" / entry["file"]
    assert sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    output = process_sample(path, settings=Settings(_env_file=None, synthetic_mode=True))
    context = RiskContext(
        duplicate_count=1 if entry.get("requires_prior") else 0,
        fingerprint="b" * 64,
        captured_at=NOW,
    )
    risk = assess(
        output.claim_data,
        output.validation,
        human_verified=False,
        context=context,
        assessed_at=NOW,
        policy=load_policy(),
    )
    assert risk.level == entry["expected_risk"]
    assert output.outcome == entry["expected_state"]
    assert output.provenance["validation_reference_date"] == MANIFEST["reference_date"]
    assert output.provenance["azure_model"] == output.provenance["llm_model"] == "not-called"


def test_fixture_dates_do_not_depend_on_machine_calendar(monkeypatch):
    class NoAmbientDate(date):
        @classmethod
        def today(cls):
            raise AssertionError("Fixture must supply its versioned reference date")

    monkeypatch.setattr(validation_module, "date", NoAmbientDate)
    output = process_sample(
        ROOT / "samples/valid.pdf", settings=Settings(_env_file=None, synthetic_mode=True)
    )
    assert output.outcome == "READY"


def test_duplicate_scenario_is_byte_identical_not_a_different_labeled_pdf():
    valid = MANIFEST["scenarios"]["valid"]
    duplicate = MANIFEST["scenarios"]["duplicate"]
    assert valid["sha256"] == duplicate["sha256"] and duplicate["requires_prior"] == "valid"


def test_conformance_report_records_no_predictive_metric():
    from scripts.check_risk_corpus import verify_corpus

    report = verify_corpus()
    assert report["all_matched"] and report["live_provider_calls"] == 0
    assert report["method"] == "synthetic_rule_conformance"
    assert len(report["cases"]) == 6
    assert {item["actual_level"] for item in report["cases"]} == {
        "LOW",
        "MEDIUM",
        "HIGH",
        "INSUFFICIENT_DATA",
        None,
    }
