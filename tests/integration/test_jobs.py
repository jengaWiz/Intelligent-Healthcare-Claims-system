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
