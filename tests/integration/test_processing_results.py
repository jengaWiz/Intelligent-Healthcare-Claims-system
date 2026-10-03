import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from models import (
    Claim,
    Document,
    ExtractionResult,
    ProcessingJob,
    RiskAssessment,
    ValidationOutcome,
)
from schema.claim_data import ClaimData
from schema.validation_result import ValidationResult
from services.extraction_service import ProcessingConflict, persist_processing_result
from services.processing import ProcessingResult

pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated migrated test database")
    engine = create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        transaction.rollback()
    engine.dispose()


def running_job(db, expired=False):
    claim = Claim(current_state="PROCESSING")
    db.add(claim)
    db.flush()
    doc = Document(
        claim_id=claim.claim_id,
        file_name="synthetic.pdf",
        file_mime_type="application/pdf",
        byte_size=10,
        sha256="0" * 64,
        storage_path="synthetic/path",
        document_state="PROCESSING",
    )
    db.add(doc)
    db.flush()
    job = ProcessingJob(
        document_id=doc.document_id,
        state="RUNNING",
        attempts=1,
        lease_owner=uuid4(),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=-30 if expired else 120),
    )
    db.add(job)
    db.flush()
    return job, doc, claim


def output(ready=True):
    raw = dict(
        patient_name="Synthetic",
        patient_dob="1980-01-01",
        provider_name="Synthetic Clinic",
        service_date="2026-10-01",
        total_amount="9007199254740993.01",
        confidence=0.9,
        reasoning="Synthetic persistence fixture",
    )
    return ProcessingResult(
        extracted_data=raw,
        claim_data=ClaimData.from_extracted_data(raw),
        validation=ValidationResult(
            is_valid=True,
            validation_score=1,
            semantic_status="completed" if ready else "unavailable",
        ),
        confidence=0.9,
        reasoning=raw["reasoning"],
        outcome="READY" if ready else "REVIEW_REQUIRED",
        provenance={"confidence_threshold": 0.8, "schema_version": "m1.1"},
    )


@pytest.mark.parametrize("ready", [True, False])
@pytest.mark.parametrize("mode", ["synthetic-fixture", "live"])
def test_processing_result_reconstructs_exactly_and_advances_states(session, ready, mode):
    job, doc, claim = running_job(session)
    processed = output(ready)
    processed.provenance["mode"] = mode
    result = persist_processing_result(session, job.job_id, job.lease_owner, processed)
    session.commit()
    session.expire_all()
    restored = session.get(ExtractionResult, result.extraction_id)
    canonical = ClaimData.model_validate(restored.normalized_data)
    assert str(canonical.billing.total_amount) == "9007199254740993.01"
    assert canonical.service.service_date.isoformat() == "2026-10-01"
    assert canonical.claim_id == str(claim.claim_id)
    assert restored.validation.semantic_status == ("completed" if ready else "unavailable")
    assert restored.provenance["job_id"] == str(job.job_id)
    assert claim.current_state == restored.outcome and claim.version == 2
    assert doc.document_state == "EXTRACTED" and job.state == "SUCCEEDED"
    assert job.lease_owner is None
    assessment = session.scalar(
        select(RiskAssessment).where(RiskAssessment.extraction_id == restored.extraction_id)
    )
    assert assessment.claim_version == claim.version
    assert assessment.level == ("HIGH" if ready else "INSUFFICIENT_DATA")
    assert "duplicate_context_unavailable" not in {item["code"] for item in assessment.signals}


def test_assessment_error_rolls_back_successful_extraction(session):
    job, document, claim = running_job(session)
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            with patch(
                "services.extraction_service.publish",
                side_effect=RuntimeError("Synthetic assessment error"),
            ):
                persist_processing_result(session, job.job_id, job.lease_owner, output())
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(ExtractionResult)) == 0
    assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
    assert (job.state, document.document_state, claim.version) == ("RUNNING", "PROCESSING", 1)


def test_lease_expiring_during_assessment_cannot_publish(session):
    from services.risk_assessment_service import publish

    job, document, claim = running_job(session)
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=1.5)
    session.flush()

    def delayed(*args, **kwargs):
        result = publish(*args, **kwargs)
        time.sleep(2)
        return result

    with pytest.raises(ProcessingConflict, match="publishing assessment"):
        with session.begin_nested():
            with patch("services.extraction_service.publish", side_effect=delayed):
                persist_processing_result(session, job.job_id, job.lease_owner, output())
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
    assert session.scalar(select(func.count()).select_from(ExtractionResult)) == 0
    assert (job.state, document.document_state, claim.version) == ("RUNNING", "PROCESSING", 1)


@pytest.mark.parametrize("expired", [True, False])
def test_expired_or_foreign_lease_cannot_publish(session, expired):
    job, doc, claim = running_job(session, expired)
    owner = job.lease_owner if expired else uuid4()
    with pytest.raises(ProcessingConflict):
        persist_processing_result(session, job.job_id, owner, output())
    assert session.scalar(select(func.count()).select_from(ExtractionResult)) == 0
    assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
    assert job.state == "RUNNING" and doc.document_state == "PROCESSING"
    assert claim.version == 1


def test_failure_rolls_back_result_validation_and_all_states(session):
    job, doc, claim = running_job(session)
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            persist_processing_result(session, job.job_id, job.lease_owner, output())
            raise RuntimeError("Synthetic caller failure")
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(ExtractionResult)) == 0
    assert session.scalar(select(func.count()).select_from(ValidationOutcome)) == 0
    assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
    assert job.state == "RUNNING" and doc.document_state == "PROCESSING"
    assert claim.current_state == "PROCESSING" and claim.version == 1


def test_inconsistent_ready_outcome_rejected(session):
    job, _, _ = running_job(session)
    result = output(False).model_copy(update={"outcome": "READY"})
    with pytest.raises(ProcessingConflict):
        persist_processing_result(session, job.job_id, job.lease_owner, result)
    assert session.scalar(select(func.count()).select_from(ExtractionResult)) == 0
