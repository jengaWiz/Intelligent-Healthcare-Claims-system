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


def test_enqueue_http_returns_committed_job_before_processing(jobs_db):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from api.main import create_app
    from services.job_lifecycle import acquire, fail_attempt
    from services.provider_errors import FailureCode, ProviderFailure

    factory, document = jobs_db
    doc = document()
    settings = Settings(_env_file=None, api_auth_token="synthetic-token")
    headers = {"Authorization": "Bearer synthetic-token", "Idempotency-Key": "http-synthetic"}
    with TestClient(create_app(settings, session_factory=factory)) as client:
        with patch("services.extraction_service.run_extraction_pipeline") as process:
            response = client.post(f"/documents/{doc}/extract", headers=headers)
            assert response.status_code == 202, response.text
            assert response.headers["retry-after"] == "2"
            assert response.json()["state"] == "QUEUED" and response.json()["attempts"] == 0
            process.assert_not_called()
        payload = response.json()
        assert (
            not {
                "lease_owner",
                "lease_expires_at",
                "idempotency_key",
                "error_code",
                "error_message",
            }
            & payload.keys()
        )
        locator = response.headers["location"]
        assert client.get(locator, headers=headers).json() == payload
        assert (
            client.post(f"/documents/{doc}/extract", headers=headers).json()["job_id"]
            == payload["job_id"]
        )
        assert client.get(locator).status_code == 401
        assert client.get(f"/jobs/{uuid4()}", headers=headers).status_code == 404
        assert (
            client.post(f"/documents/{uuid4()}/extract", headers=headers).status_code == 409
        )  # key belongs elsewhere
        assert (
            client.post(
                f"/documents/{doc}/extract", headers={**headers, "Idempotency-Key": "bad key"}
            ).status_code
            == 422
        )
        with factory.begin() as db:
            lease = acquire(db, settings)
        with factory.begin() as db:
            fail_attempt(db, lease, ProviderFailure("ocr", FailureCode.INVALID_RESPONSE))
        polled = client.get(locator, headers=headers).json()
        assert (
            polled["state"] == "FAILED" and polled["error"]["code"] == "invalid_provider_response"
        )
        fresh = client.post(
            f"/documents/{doc}/extract", headers={**headers, "Idempotency-Key": "fresh-http"}
        )
        assert fresh.status_code == 202 and fresh.json()["job_id"] != payload["job_id"]
        assert (
            client.post(f"/documents/{doc}/extract", headers=headers).json()["job_id"]
            == payload["job_id"]
        )


def processing_output():
    from schema.claim_data import ClaimData
    from schema.validation_result import ValidationResult
    from services.processing import ProcessingResult

    raw = dict(
        patient_name="Synthetic",
        patient_dob="1980-01-01",
        provider_name="Synthetic Clinic",
        service_date="2026-10-01",
        total_amount="42.50",
        confidence=0.9,
        reasoning="Synthetic fixture",
    )
    return ProcessingResult(
        extracted_data=raw,
        claim_data=ClaimData.from_extracted_data(raw),
        validation=ValidationResult(is_valid=True, validation_score=1, semantic_status="completed"),
        confidence=0.9,
        reasoning=raw["reasoning"],
        outcome="READY",
        provenance={"confidence_threshold": 0.8},
    )


def worker_document(factory, document, tmp_path):
    doc = document()
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-synthetic")
    with factory.begin() as db:
        db.get(Document, doc).storage_path = str(path)
    return doc


def test_worker_completes_with_independent_sessions_and_one_result(jobs_db, tmp_path):
    from models import ExtractionResult
    from worker.runtime import run_once

    factory, document = jobs_db
    settings = Settings(_env_file=None, upload_dir=tmp_path)
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id

    def process(path, **kwargs):
        # The lease transaction is committed and readable through another session.
        with factory() as db:
            assert db.get(ProcessingJob, job_id).state == "RUNNING"
        return processing_output()

    assert run_once(factory, settings, processor=process)
    assert not run_once(factory, settings, processor=process)
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "SUCCEEDED" and job.document.claim.current_state == "READY"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExtractionResult)
                .where(ExtractionResult.job_id == job_id)
            )
            == 1
        )
    with pytest.raises(JobError):
        with factory.begin() as db:
            enqueue(db, doc, settings)


def test_worker_failure_persists_safe_terminal_status(jobs_db, tmp_path):
    from worker.runtime import run_once

    factory, document = jobs_db
    settings = Settings(_env_file=None, upload_dir=tmp_path)
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic private content and key")

    assert run_once(factory, settings, processor=broken)
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "FAILED"
        assert "synthetic private" not in job.error_message


def test_worker_heartbeats_during_provider_work(jobs_db, tmp_path):
    from threading import Event

    from worker.runtime import run_once

    factory, document = jobs_db
    settings = Settings(
        _env_file=None,
        upload_dir=tmp_path,
        job_heartbeat_seconds=1,
        job_lease_seconds=10,
        provider_timeout_seconds=1,
    )
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id
    started, release = Event(), Event()

    def slow(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return processing_output()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_once, factory, settings, processor=slow)
        assert started.wait(timeout=5)
        with factory() as db:
            initial = db.get(ProcessingJob, job_id).lease_expires_at
        try:
            import time

            deadline = time.monotonic() + 4
            extended = False
            while time.monotonic() < deadline:
                with factory() as db:
                    extended = db.get(ProcessingJob, job_id).lease_expires_at > initial
                if extended:
                    break
                time.sleep(0.1)
            assert extended
        finally:
            release.set()
        assert future.result(timeout=5)


def test_process_crash_then_new_worker_recovers(jobs_db, tmp_path):
    import subprocess
    import sys
    from datetime import datetime, timedelta, timezone

    factory, document = jobs_db
    settings = Settings(_env_file=None, upload_dir=tmp_path)
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id
    code = """
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.settings import Settings
from services.job_lifecycle import acquire
engine=create_engine(os.environ["TEST_DATABASE_URL"])
factory=sessionmaker(bind=engine,autoflush=False)
with factory.begin() as db:
    assert acquire(db, Settings(_env_file=None)) is not None
os._exit(9)
"""
    crashed = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=15)
    assert crashed.returncode == 9
    with factory.begin() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "RUNNING" and job.attempts == 1
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    payload = tmp_path / "output.json"
    payload.write_text(processing_output().model_dump_json())
    env = {**os.environ, "TEST_UPLOAD_DIR": str(tmp_path), "TEST_OUTPUT_FILE": str(payload)}
    recovery = """
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.settings import Settings
from services.processing import ProcessingResult
from worker.runtime import run_once
engine=create_engine(os.environ["TEST_DATABASE_URL"])
factory=sessionmaker(bind=engine,autoflush=False)
output=ProcessingResult.model_validate_json(Path(os.environ["TEST_OUTPUT_FILE"]).read_text())
assert run_once(factory,Settings(_env_file=None,upload_dir=os.environ["TEST_UPLOAD_DIR"]),
                processor=lambda *args,**kwargs:output)
engine.dispose()
"""
    restarted = subprocess.run(
        [sys.executable, "-c", recovery], env=env, capture_output=True, timeout=15
    )
    assert restarted.returncode == 0
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "SUCCEEDED" and job.attempts == 2


def test_active_request_alias_does_not_deadlock_with_worker_job_lock(jobs_db):
    factory, document = jobs_db
    settings = Settings(_env_file=None)
    doc = document()
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id
    with factory.begin() as worker:
        worker.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.job_id == job_id)
            .with_for_update(key_share=True)
        )
        # This adds a foreign key to the job while the worker owns its row lock.
        with ThreadPoolExecutor(max_workers=1) as pool:

            def duplicate():
                with factory.begin() as request:
                    return enqueue(request, doc, settings, "late-key").job_id

            assert pool.submit(duplicate).result(timeout=5) == job_id


def test_concurrent_key_reuse_across_documents_conflicts(jobs_db):
    factory, document = jobs_db
    documents = [document(), document()]
    barrier = Barrier(2)

    def submit(doc):
        barrier.wait(timeout=5)
        try:
            with factory.begin() as db:
                return (202, enqueue(db, doc, Settings(_env_file=None), "shared-key").job_id)
        except JobError as error:
            return (error.status, None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, documents))
    assert sorted(status for status, _ in outcomes) == [202, 409]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(JobRequest).where(JobRequest.key == "shared-key")
            )
            == 1
        )


def test_stale_worker_cannot_publish_after_recovery(jobs_db, tmp_path):
    from datetime import datetime, timedelta, timezone

    from models import ExtractionResult
    from services.extraction_service import persist_processing_result
    from services.job_lifecycle import acquire
    from worker.runtime import run_once

    factory, document = jobs_db
    settings = Settings(_env_file=None, upload_dir=tmp_path)
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id
    owners = []

    def slow_old_worker(*args, **kwargs):
        with factory.begin() as db:
            db.get(ProcessingJob, job_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
        with factory.begin() as db:
            owners.append(acquire(db, settings))
        return processing_output()

    assert run_once(factory, settings, processor=slow_old_worker)
    with factory() as db:
        assert db.get(ProcessingJob, job_id).state == "RUNNING"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExtractionResult)
                .where(ExtractionResult.job_id == job_id)
            )
            == 0
        )
    with factory.begin() as db:
        persist_processing_result(db, job_id, owners[0].owner, processing_output())
    with factory() as db:
        assert db.get(ProcessingJob, job_id).state == "SUCCEEDED"


def test_transient_failures_stop_at_attempt_budget(jobs_db, tmp_path):
    from datetime import datetime, timedelta, timezone

    from services.provider_errors import FailureCode, ProviderFailure
    from worker.runtime import run_once

    factory, document = jobs_db
    settings = Settings(_env_file=None, upload_dir=tmp_path, job_max_attempts=2)
    doc = worker_document(factory, document, tmp_path)
    with factory.begin() as db:
        job_id = enqueue(db, doc, settings).job_id

    def timeout(*args, **kwargs):
        raise ProviderFailure("ocr", FailureCode.TIMEOUT, True)

    assert run_once(factory, settings, processor=timeout)
    with factory.begin() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "RETRY_WAIT"
        job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert run_once(factory, settings, processor=timeout)
    with factory() as db:
        job = db.get(ProcessingJob, job_id)
        assert job.state == "FAILED" and job.attempts == 2
        assert job.next_attempt_at is None and job.lease_owner is None
