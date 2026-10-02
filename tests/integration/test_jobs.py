import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from models import Claim, Document, JobRequest, ProcessingJob
from services.job_service import JobError, enqueue

pytestmark = pytest.mark.integration


@pytest.fixture
def jobs_db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated dedicated test database")
    engine = create_engine(url, hide_parameters=True)
    factory = sessionmaker(bind=engine, autoflush=False)
    ids = []

    def document():
        with factory.begin() as db:
            claim = Claim()
            db.add(claim)
            db.flush()
            ids.append(claim.claim_id)
            doc = Document(
                claim_id=claim.claim_id,
                file_name="synthetic.pdf",
                file_mime_type="application/pdf",
                byte_size=10,
                sha256="0" * 64,
                storage_path="synthetic.pdf",
            )
            db.add(doc)
            db.flush()
            return doc.document_id

    yield factory, document
    with factory.begin() as db:
        db.execute(delete(Claim).where(Claim.claim_id.in_(ids)))
    engine.dispose()


def test_duplicate_keys_remain_bound_to_original_job(jobs_db):
    factory, document = jobs_db
    doc = document()
    settings = Settings(_env_file=None)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings, "first").job_id
    with factory.begin() as db:
        assert enqueue(db, doc, settings, "second").job_id == job_id
    with factory.begin() as db:
        job = db.get(ProcessingJob, job_id)
        job.state = "FAILED"
        record = db.get(Document, doc)
        record.document_state = "FAILED"
        record.claim.current_state = "FAILED"
    with factory.begin() as db:
        assert enqueue(db, doc, settings, "second").job_id == job_id
        fresh = enqueue(db, doc, settings, "third")
        assert fresh.job_id != job_id
    other = document()
    with pytest.raises(JobError) as caught:
        with factory.begin() as db:
            enqueue(db, other, settings, "second")
    assert caught.value.status == 409


def test_concurrent_enqueue_accepts_one_active_job(jobs_db):
    factory, document = jobs_db
    doc = document()
    barrier = Barrier(2)

    def submit(key):
        barrier.wait(timeout=5)
        with factory.begin() as db:
            return enqueue(db, doc, Settings(_env_file=None), key).job_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(submit, [str(uuid4()), str(uuid4())]))
    assert ids[0] == ids[1]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(ProcessingJob.document_id == doc)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(JobRequest).where(JobRequest.document_id == doc)
            )
            == 2
        )


def test_missing_and_ineligible_document_rejected(jobs_db):
    factory, document = jobs_db
    with pytest.raises(JobError) as caught:
        with factory.begin() as db:
            enqueue(db, uuid4(), Settings(_env_file=None))
    assert caught.value.status == 404
    doc = document()
    with factory.begin() as db:
        db.get(Document, doc).document_state = "EXTRACTED"
    with pytest.raises(JobError) as caught:
        with factory.begin() as db:
            enqueue(db, doc, Settings(_env_file=None))
    assert caught.value.status == 409


def test_recovery_uses_new_owner_and_exhausts_crash_loop(jobs_db):
    from datetime import datetime, timedelta, timezone

    from services.job_lifecycle import acquire, heartbeat

    factory, document = jobs_db
    settings = Settings(_env_file=None, job_max_attempts=2)
    with factory.begin() as db:
        job_id = enqueue(db, document(), settings).job_id
    with factory.begin() as db:
        first = acquire(db, settings)
        assert first.job_id == job_id and first.attempts == 1
    with factory.begin() as db:
        db.get(ProcessingJob, job_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
    with factory.begin() as db:
        second = acquire(db, settings)
        assert second.owner != first.owner and second.attempts == 2
    with factory.begin() as db:
        assert not heartbeat(db, first, settings)
        assert heartbeat(db, second, settings)
        db.get(ProcessingJob, job_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
    with factory.begin() as db:
        assert acquire(db, settings) is None
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "FAILED" and job.attempts == 2
        assert job.document.document_state == "FAILED"
        assert job.document.claim.current_state == "FAILED"


def test_transient_retry_waits_and_permanent_failure_stops(jobs_db):
    from datetime import datetime, timedelta, timezone

    from services.job_lifecycle import acquire, fail_attempt
    from services.provider_errors import FailureCode, ProviderFailure

    factory, document = jobs_db
    settings = Settings(_env_file=None)
    with factory.begin() as db:
        job_id = enqueue(db, document(), settings).job_id
    with factory.begin() as db:
        lease = acquire(db, settings)
    with factory.begin() as db:
        fail_attempt(db, lease, ProviderFailure("ocr", FailureCode.RATE_LIMITED, True, 999))
        job = db.get(ProcessingJob, job_id)
        remaining = (job.next_attempt_at - datetime.now(timezone.utc)).total_seconds()
        assert 58 < remaining <= 60
        assert job.document.document_state == "QUEUED"
    with factory.begin() as db:
        assert acquire(db, settings) is None
        db.get(ProcessingJob, job_id).next_attempt_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
    with factory.begin() as db:
        retry = acquire(db, settings)
        assert retry.attempts == 2
    with factory.begin() as db:
        fail_attempt(db, retry, ProviderFailure("extraction", FailureCode.INVALID_RESPONSE))
    with factory() as db:
        assert db.get(ProcessingJob, job_id).state == "FAILED"


def test_workers_skip_locked_jobs(jobs_db):
    from services.job_lifecycle import acquire

    factory, document = jobs_db
    settings = Settings(_env_file=None)
    for _ in range(2):
        with factory.begin() as db:
            enqueue(db, document(), settings)
    with factory.begin() as first:
        lease1 = acquire(first, settings)
        with factory.begin() as second:
            lease2 = acquire(second, settings)
            assert lease1.job_id != lease2.job_id
