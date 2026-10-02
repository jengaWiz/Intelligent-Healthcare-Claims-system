"""Process one leased job outside DB transactions, with independent heartbeats."""

import logging
from pathlib import Path
from threading import Event, Thread

from services.extraction_service import (
    ProcessingConflict,
    persist_processing_result,
    run_extraction_pipeline,
)
from services.job_lifecycle import acquire, fail_attempt, heartbeat
from services.provider_errors import FailureCode, ProviderFailure, classify_failure

logger = logging.getLogger(__name__)


class LeaseHeartbeat:
    def __init__(self, factory, lease, settings):
        self.factory, self.lease, self.settings = factory, lease, settings
        self.stop = Event()
        self.lost = Event()
        self.thread = Thread(target=self.run, name="job-heartbeat", daemon=True)

    def run(self):
        while not self.stop.wait(self.settings.job_heartbeat_seconds):
            try:
                with self.factory.begin() as db:
                    if not heartbeat(db, self.lease, self.settings):
                        self.lost.set()
                        return
            except Exception:
                # Never continue publishing under unconfirmed ownership.
                self.lost.set()
                logger.warning("Worker heartbeat unavailable; job_id=%s", self.lease.job_id)
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()  # DB timeouts bound in-flight heartbeats in the CLI engine.


def run_once(factory, settings, *, processor=run_extraction_pipeline):
    with factory.begin() as db:
        lease = acquire(db, settings)
    if lease is None:
        return False
    failure = None
    with LeaseHeartbeat(factory, lease, settings) as guard:
        try:
            path = Path(lease.document_path).resolve()
            if path.parent != settings.upload_dir.resolve() or not path.is_file():
                raise ProviderFailure("ocr", FailureCode.DOCUMENT_READ)
            output = processor(str(path), settings=settings)
        except Exception as exc:
            failure = classify_failure(exc, "processing")
        if guard.lost.is_set():
            return True  # Let expiry/recovery handle unconfirmed ownership.
        try:
            with factory.begin() as db:
                if failure is None:
                    persist_processing_result(db, lease.job_id, lease.owner, output)
                else:
                    fail_attempt(db, lease, failure)
        except ProcessingConflict:
            logger.info("Worker completion lease lost; job_id=%s", lease.job_id)
        # Other persistence errors leave RUNNING intact. Caller reports only a safe
        # database code, and expiry can recover a rolled-back or uncertain completion.
    return True
