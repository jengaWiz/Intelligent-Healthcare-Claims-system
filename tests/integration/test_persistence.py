"""PostgreSQL behavior checks; requires a dedicated already-migrated test database."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Claim, Document, ExtractionResult, ProcessingJob, Review, ValidationOutcome
from services.claim_service import create_claim

pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated migrated PostgreSQL database")
    engine = create_engine(url)
    # Every test is isolated in an outer rollback, even if it commits a nested session.
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            yield db
        transaction.rollback()
    engine.dispose()


def document(db):
    claim = create_claim(db, "synthetic-test")
    doc = Document(
        claim_id=claim.claim_id,
        file_name="synthetic.pdf",
        file_mime_type="application/pdf",
        byte_size=100,
        sha256="0" * 64,
        storage_path="synthetic/path",
    )
    db.add(doc)
    db.flush()
    return doc


def test_persist_load_relationships_and_database_cascade(session):
    doc = document(session)
    job = ProcessingJob(document_id=doc.document_id, state="SUCCEEDED", attempts=1)
    session.add(job)
    session.flush()
    result = ExtractionResult(
        document_id=doc.document_id,
        job_id=job.job_id,
        extracted_data={"patient_name": "Synthetic Patient"},
        normalized_data={"billing": {"total_amount": "150.00"}},
        confidence=0.9,
        outcome="READY",
        extraction_engine="fake",
        extraction_version="m1",
        provenance={"model": "fake"},
    )
    result.validation = ValidationOutcome(
        is_valid=True, validation_score=1, semantic_status="completed"
    )
    session.add(result)
    review = Review(
        claim_id=doc.claim_id,
        actor_id="synthetic-reviewer",
        decision="approve",
        reason="Verified synthetic source",
        previous_version=1,
        new_version=2,
        before_data={},
        after_data={},
    )
    session.add(review)
    session.flush()
    claim_id = doc.claim_id
    session.expire_all()
    claim = session.get(Claim, claim_id)
    assert claim.documents[0].extraction_result.validation.is_valid
    assert claim.documents[0].jobs[0].job_id == job.job_id
    assert claim.reviews[0].actor_id == "synthetic-reviewer"
    # Clear identity map to test ON DELETE CASCADE independently of ORM loaded children.
    session.expunge_all()
    session.delete(session.get(Claim, claim_id))
    session.flush()
    for model in (Claim, Document, ProcessingJob, ExtractionResult, ValidationOutcome, Review):
        assert session.scalar(select(func.count()).select_from(model)) == 0


def test_one_document_per_claim_and_foreign_keys(session):
    doc = document(session)
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                Document(
                    claim_id=doc.claim_id,
                    file_name="second.pdf",
                    file_mime_type="application/pdf",
                    byte_size=100,
                    sha256="0" * 64,
                    storage_path="second/path",
                )
            )
            session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(ProcessingJob(document_id=uuid.uuid4()))
            session.flush()


def test_active_job_uniqueness_and_failed_retry(session):
    doc = document(session)
    first = ProcessingJob(document_id=doc.document_id)
    session.add(first)
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(ProcessingJob(document_id=doc.document_id))
            session.flush()
    first.state = "FAILED"
    session.flush()
    retry = ProcessingJob(document_id=doc.document_id)
    session.add(retry)
    session.flush()
    assert retry.job_id != first.job_id


def test_transaction_rollback_does_not_persist_claim_or_document(session):
    with pytest.raises(RuntimeError):
        with session.begin_nested():
            doc = document(session)
            claim_id = doc.claim_id
            raise RuntimeError("synthetic pipeline failure")
    assert session.get(Claim, claim_id) is None
    assert session.scalar(select(func.count()).select_from(Document)) == 0


@pytest.mark.parametrize(
    "model,values",
    [
        (Claim, {"current_state": "INSURANCE_APPROVED"}),
        (Claim, {"version": 0}),
    ],
)
def test_invalid_claim_constraints(session, model, values):
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(model(**values))
            session.flush()


def test_job_attempt_and_lease_constraints(session):
    doc = document(session)
    for values in ({"attempts": 4, "max_attempts": 3}, {"state": "RUNNING"}):
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(ProcessingJob(document_id=doc.document_id, **values))
                session.flush()


def test_result_uniqueness_and_confidence_bounds(session):
    doc = document(session)
    job = ProcessingJob(document_id=doc.document_id, state="SUCCEEDED", attempts=1)
    session.add(job)
    session.flush()
    values = dict(
        document_id=doc.document_id,
        job_id=job.job_id,
        extracted_data={},
        normalized_data={},
        outcome="READY",
        extraction_engine="fake",
        extraction_version="m1",
        provenance={},
    )
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(ExtractionResult(confidence=1.1, **values))
            session.flush()
    session.add(ExtractionResult(confidence=0.9, **values))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(ExtractionResult(confidence=0.9, **values))
            session.flush()


def test_review_revision_uniqueness(session):
    doc = document(session)
    values = dict(
        claim_id=doc.claim_id,
        actor_id="synthetic",
        decision="correct",
        reason="synthetic correction",
        previous_version=1,
        new_version=2,
        before_data={},
        after_data={},
    )
    session.add(Review(**values))
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(Review(**values))
            session.flush()
