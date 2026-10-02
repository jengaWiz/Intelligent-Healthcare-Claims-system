"""Review evidence, state/version conflicts, and HTTP projections on PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from api.dependencies import APIError
from api.main import create_app
from config.settings import Settings
from models import Document, ExtractionResult
from schema.review import ReviewCreate
from services.extraction_service import persist_processing_result
from services.job_lifecycle import acquire
from services.job_service import enqueue
from services.review_service import decide
from tests.integration.test_jobs import jobs_db as _jobs_db
from tests.integration.test_jobs import processing_output

jobs_db = _jobs_db

pytestmark = pytest.mark.integration
HEADERS = {"Authorization": "Bearer synthetic-token"}


def completed(factory, document, *, fixture_mode=False):
    doc = document()
    output = processing_output()
    if fixture_mode:
        output.provenance["mode"] = "synthetic-fixture"
    output.confidence = 0.5
    output.outcome = "REVIEW_REQUIRED"
    with factory.begin() as db:
        enqueue(db, doc, Settings(_env_file=None))
    with factory.begin() as db:
        lease = acquire(db, Settings(_env_file=None))
    with factory.begin() as db:
        result = persist_processing_result(db, lease.job_id, lease.owner, output)
        claim = db.get(Document, doc).claim
        return claim.claim_id, claim.version, result.extraction_id


def test_results_correction_and_immutable_history(jobs_db):
    factory, document = jobs_db
    claim_id, version, extraction_id = completed(factory, document)
    with TestClient(
        create_app(
            Settings(_env_file=None, api_auth_token="synthetic-token"), session_factory=factory
        )
    ) as client:
        path = f"/claims/{claim_id}"
        assert client.get(path + "/results").status_code == 401
        original = client.get(path + "/results", headers=HEADERS).json()
        assert original["current"]["data"]["billing"]["total_amount"] == "42.50"
        assert client.get("/reviews", headers=HEADERS).json()[0]["claim_id"] == str(claim_id)
        payload = {
            "expected_version": version,
            "decision": "correct",
            "reason": "Compared synthetic source",
            "corrections": {
                "patient_name": "Synthetic Corrected",
                "patient_dob": "1980-01-01",
                "provider_name": "Synthetic Clinic",
                "service_date": "2026-10-01",
                "total_amount": "48.75",
            },
        }
        bad = {**payload, "corrections": {**payload["corrections"], "service_date": "2099-01-01"}}
        assert client.post(path + "/reviews", headers=HEADERS, json=bad).status_code == 422
        result = client.post(path + "/reviews", headers=HEADERS, json=payload)
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["claim"]["state"] == "READY" and data["claim"]["version"] == version + 1
        assert data["current"]["data"]["billing"]["total_amount"] == "48.75"
        assert data["extraction"] == original["extraction"]
        assert data["reviews"][0]["before_data"]["data"]["billing"]["total_amount"] == "42.50"
        assert client.post(path + "/reviews", headers=HEADERS, json=payload).status_code == 409
        payload["expected_version"] += 1
        assert client.post(path + "/reviews", headers=HEADERS, json=payload).status_code == 409
        assert len(client.get(path + "/reviews", headers=HEADERS).json()) == 1
    with factory() as db:
        assert (
            db.get(ExtractionResult, extraction_id).normalized_data["billing"]["total_amount"]
            == "42.50"
        )


def test_concurrent_reviews_one_decision_and_rejection(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)
    barrier = Barrier(2)
    payload = ReviewCreate(
        expected_version=version, decision="reject", reason="Synthetic unreadable source"
    )

    def submit(_):
        barrier.wait(timeout=5)
        try:
            with factory.begin() as db:
                return decide(db, claim_id, payload, "synthetic-reviewer")["claim"].state
        except APIError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, range(2)))
    assert set(outcomes) == {"REJECTED", 409}


def test_pending_result_has_no_extraction(jobs_db):
    factory, document = jobs_db
    doc = document()
    with factory() as db:
        claim_id = db.get(Document, doc).claim_id
    with TestClient(
        create_app(
            Settings(_env_file=None, api_auth_token="synthetic-token"), session_factory=factory
        )
    ) as client:
        result = client.get(f"/claims/{claim_id}/results", headers=HEADERS).json()
        assert result["claim"]["state"] == "RECEIVED"
        assert result["extraction"] is None and result["current"] is None


def test_fixture_engine_matches_recorded_provenance(jobs_db):
    factory, document = jobs_db
    _, _, extraction_id = completed(factory, document, fixture_mode=True)
    with factory() as db:
        result = db.get(ExtractionResult, extraction_id)
        assert result.extraction_engine == "SyntheticFixture"
        assert result.provenance["mode"] == "synthetic-fixture"
