"""Corrections, risk refresh and conflicts preserve immutable evidence."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from api.dependencies import APIError
from models import Claim, ExtractionResult, Review
from schema.review import ReviewCreate
from schema.risk import RiskAcknowledgmentCreate, RiskRefreshCreate
from services import risk_storage
from services.review_service import decide
from services.risk_assessment_service import refresh
from tests.integration.test_jobs import jobs_db as _jobs_db
from tests.integration.test_reviews import completed

jobs_db = _jobs_db
pytestmark = pytest.mark.integration


def correction(version, amount="100001"):
    return ReviewCreate(
        expected_version=version,
        decision="correct",
        reason="Checked synthetic source",
        corrections={
            "patient_name": "Synthetic",
            "provider_name": "Clinic",
            "service_date": "2026-10-01",
            "total_amount": amount,
        },
    )


def test_correction_reassessment_refresh_and_original_evidence(jobs_db):
    factory, document = jobs_db
    claim_id, version, extraction_id = completed(factory, document)
    with factory.begin() as db:
        first = risk_storage.current(db, claim_id)
        assert "unverified_extraction" in {item.code for item in first.signals}
        risk_storage.acknowledge(
            db,
            claim_id,
            RiskAcknowledgmentCreate(
                expected_version=version,
                assessment_id=first.assessment_id,
                reason="Checked prior assessment",
            ),
            "api",
        )
        decide(db, claim_id, correction(version), "api")
        second = risk_storage.current(db, claim_id)
        assert second.claim_version == version + 1
        assert "amount_high" in {item.code for item in second.signals}
        assert second.level == "HIGH"
        assert "unverified_extraction" not in {item.code for item in second.signals}
        assert second.assessment_id != first.assessment_id
        assert (
            db.get(ExtractionResult, extraction_id).normalized_data["billing"]["total_amount"]
            == "42.50"
        )
        assert (
            refresh(db, claim_id, RiskRefreshCreate(expected_version=version + 1)).assessment_id
            == second.assessment_id
        )
        assert len(risk_storage.history(db, claim_id)) == 2
        with pytest.raises(APIError) as error:
            risk_storage.acknowledge(
                db,
                claim_id,
                RiskAcknowledgmentCreate(
                    expected_version=version + 1,
                    assessment_id=first.assessment_id,
                    reason="Checked prior assessment",
                ),
                "api",
            )
        assert error.value.code == "stale_assessment"


def test_assessment_failure_rolls_back_correction(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)
    with pytest.raises(RuntimeError):
        with factory.begin() as db:
            with patch(
                "services.review_service.publish", side_effect=RuntimeError("Synthetic failure")
            ):
                decide(db, claim_id, correction(version), "api")
    with factory() as db:
        claim = db.get(Claim, claim_id)
        assert (claim.version, claim.current_state) == (version, "REVIEW_REQUIRED")
        assert (
            db.scalar(select(func.count()).select_from(Review).where(Review.claim_id == claim_id))
            == 0
        )
        assert len(risk_storage.history(db, claim_id)) == 1


def test_refresh_rejects_stale_missing_and_inactive_sources(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)
    with factory.begin() as db:
        with pytest.raises(APIError) as error:
            refresh(db, claim_id, RiskRefreshCreate(expected_version=version - 1))
        assert error.value.code == "stale_risk"
        decide(
            db,
            claim_id,
            ReviewCreate(expected_version=version, decision="reject", reason="Synthetic rejection"),
            "api",
        )
        assert len(risk_storage.history(db, claim_id)) == 2
        with pytest.raises(APIError) as error:
            refresh(db, claim_id, RiskRefreshCreate(expected_version=version + 1))
        assert error.value.code == "risk_inactive"
    doc_id = document()
    from models import Document

    with factory.begin() as db:
        claim_id = db.get(Document, doc_id).claim_id
        with pytest.raises(APIError) as error:
            refresh(db, claim_id, RiskRefreshCreate(expected_version=1))
        assert error.value.code == "risk_source_unavailable"


def test_concurrent_correction_and_refresh_end_on_current_version(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)

    def change():
        with factory.begin() as db:
            return decide(db, claim_id, correction(version, "48.75"), "api")["claim"].version

    def reread():
        try:
            with factory.begin() as db:
                return refresh(
                    db, claim_id, RiskRefreshCreate(expected_version=version)
                ).claim_version
        except APIError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed = pool.submit(change)
        refreshed = pool.submit(reread)
        assert changed.result(timeout=10) == version + 1
        assert refreshed.result(timeout=10) in (version, "stale_risk")
    with factory() as db:
        assert risk_storage.current(db, claim_id).claim_version == version + 1
        assert len(risk_storage.history(db, claim_id)) == 2
