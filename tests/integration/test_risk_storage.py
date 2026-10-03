"""Real PostgreSQL risk identity, immutable history, scoping and rollback."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import APIError
from models import (
    Claim,
    Document,
    ExtractionResult,
    ProcessingJob,
    RiskAcknowledgment,
    RiskAssessment,
)
from schema.risk import RiskAcknowledgmentCreate, RiskEvaluation
from services import risk_storage

pytestmark = pytest.mark.integration


@pytest.fixture
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated dedicated PostgreSQL database")
    engine = create_engine(url, hide_parameters=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def source(db, owner="risk-test"):
    claim = Claim(owner_id=owner, current_state="READY")
    db.add(claim)
    db.flush()
    document = Document(
        claim_id=claim.claim_id,
        file_name="synthetic.pdf",
        file_mime_type="application/pdf",
        byte_size=10,
        sha256="a" * 64,
        storage_path="synthetic/path",
        document_state="EXTRACTED",
    )
    db.add(document)
    db.flush()
    job = ProcessingJob(document_id=document.document_id, state="SUCCEEDED", attempts=1)
    db.add(job)
    db.flush()
    result = ExtractionResult(
        document_id=document.document_id,
        job_id=job.job_id,
        extracted_data={},
        normalized_data={},
        confidence=0.95,
        outcome="READY",
        extraction_engine="SyntheticFixture",
        extraction_version="test",
        provenance={},
    )
    db.add(result)
    db.flush()
    return claim, result


def evaluation(context="b"):
    return RiskEvaluation(
        level="LOW",
        policy_version="risk-v1",
        signals=[],
        input_fingerprint="a" * 64,
        context_fingerprint=context * 64,
        assessed_at=datetime.now(UTC),
        context_at=datetime.now(UTC),
    )


def store(db, claim, result, context="b"):
    return risk_storage.store(
        db,
        claim.claim_id,
        result.extraction_id,
        evaluation(context),
        expected_version=claim.version,
    )


def test_legacy_null_dedup_and_context_round_trip(db):
    claim, result = source(db)
    assert risk_storage.current(db, claim.claim_id) is None
    first = store(db, claim, result)
    assert store(db, claim, result).assessment_id == first.assessment_id
    second = store(db, claim, result, "c")
    third = store(db, claim, result, "b")
    assert (first.revision, second.revision, third.revision) == (1, 2, 3)
    history = risk_storage.history(db, claim.claim_id, limit=2)
    assert [item.assessment_id for item in history] == [third.assessment_id, second.assessment_id]
    assert "input_fingerprint" not in history[0].model_dump(mode="json")
    assert (
        risk_storage.history(db, claim.claim_id, limit=2, offset=2)[0].assessment_id
        == first.assessment_id
    )


def test_source_mismatch_rejected_by_service_and_database(db):
    claim, result = source(db)
    other, _ = source(db)
    with pytest.raises(APIError) as error:
        risk_storage.store(
            db, other.claim_id, result.extraction_id, evaluation(), expected_version=1
        )
    assert error.value.code == "risk_source_unavailable"
    first = store(db, claim, result)
    values = {
        column.name: getattr(first, column.name) for column in RiskAssessment.__table__.columns
    }
    values.pop("assessment_id")
    values["claim_id"] = other.claim_id
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(RiskAssessment(**values))
            db.flush()


def test_ack_replay_and_new_assessment_does_not_inherit_ack(db):
    claim, result = source(db)
    first = store(db, claim, result)
    payload = RiskAcknowledgmentCreate(
        expected_version=1, assessment_id=first.assessment_id, reason="Checked synthetic document"
    )
    record = risk_storage.acknowledge(db, claim.claim_id, payload, "risk-test")
    assert (
        risk_storage.acknowledge(db, claim.claim_id, payload, "risk-test").acknowledgment_id
        == record.acknowledgment_id
    )
    assert risk_storage.project_ack(record).reason == payload.reason
    with pytest.raises(APIError) as error:
        risk_storage.acknowledge(
            db, claim.claim_id, payload.model_copy(update={"reason": "Different"}), "risk-test"
        )
    assert error.value.code == "risk_already_acknowledged"
    second = store(db, claim, result, "c")
    with pytest.raises(APIError) as error:
        risk_storage.acknowledge(db, claim.claim_id, payload, "risk-test")
    assert error.value.code == "stale_assessment"
    assert (
        db.scalar(
            select(func.count())
            .select_from(RiskAcknowledgment)
            .where(RiskAcknowledgment.assessment_id == second.assessment_id)
        )
        == 0
    )


def test_database_rejects_history_updates(db):
    claim, result = source(db)
    assessment = store(db, claim, result)
    record = risk_storage.acknowledge(
        db,
        claim.claim_id,
        RiskAcknowledgmentCreate(
            expected_version=1, assessment_id=assessment.assessment_id, reason="Investigated"
        ),
        "risk-test",
    )
    for statement in (
        update(RiskAssessment)
        .where(RiskAssessment.assessment_id == assessment.assessment_id)
        .values(level="HIGH"),
        update(RiskAcknowledgment)
        .where(RiskAcknowledgment.acknowledgment_id == record.acknowledgment_id)
        .values(reason="Rewritten"),
    ):
        with pytest.raises(DBAPIError, match="Risk history is immutable"):
            with db.begin_nested():
                db.execute(statement)
    db.expire_all()
    assert assessment.level == "LOW" and record.reason == "Investigated"


def test_rollback_cascade_and_stale_version(db):
    claim, result = source(db)
    with pytest.raises(RuntimeError):
        with db.begin_nested():
            store(db, claim, result)
            raise RuntimeError("Rollback fixture")
    assert risk_storage.current(db, claim.claim_id) is None
    store(db, claim, result)
    claim.version += 1
    db.flush()
    assert risk_storage.current(db, claim.claim_id) is None
    with pytest.raises(APIError) as error:
        risk_storage.store(
            db, claim.claim_id, result.extraction_id, evaluation(), expected_version=1
        )
    assert error.value.code == "stale_risk"
    db.execute(delete(Claim).where(Claim.claim_id == claim.claim_id))
    assert (
        db.scalar(
            select(func.count())
            .select_from(RiskAssessment)
            .where(RiskAssessment.claim_id == claim.claim_id)
        )
        == 0
    )


def test_read_write_scope_and_actor_boundaries(db):
    claim, result = source(db)
    assessment = store(db, claim, result)
    db.info["actor_id"] = "stranger"
    for operation in (
        lambda: risk_storage.history(db, claim.claim_id),
        lambda: risk_storage.current(db, claim.claim_id),
        lambda: store(db, claim, result),
    ):
        with pytest.raises(APIError) as error:
            operation()
        assert error.value.status == 404
    db.info["actor_id"] = "risk-test"
    with pytest.raises(APIError) as error:
        risk_storage.acknowledge(
            db,
            claim.claim_id,
            RiskAcknowledgmentCreate(
                expected_version=1, assessment_id=assessment.assessment_id, reason="Checked"
            ),
            "stranger",
        )
    assert error.value.code == "actor_mismatch"


def test_concurrent_identical_assessments_publish_once(engine):
    with Session(engine) as db:
        claim, result = source(db)
        claim_id, extraction_id = claim.claim_id, result.extraction_id
        db.commit()
    try:

        def publish(_):
            with Session(engine) as db, db.begin():
                return risk_storage.store(
                    db, claim_id, extraction_id, evaluation(), expected_version=1
                ).assessment_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(publish, range(2)))
        assert ids[0] == ids[1]
        with Session(engine) as db:
            assert len(risk_storage.history(db, claim_id)) == 1
    finally:
        with Session(engine) as db, db.begin():
            db.execute(delete(Claim).where(Claim.claim_id == claim_id))
