"""Durable enqueue/state operations. Callers own short database transactions."""

import hashlib
import re

from sqlalchemy import func, select

from models import Claim, Document, JobRequest, ProcessingJob

ACTIVE = ("QUEUED", "RUNNING", "RETRY_WAIT")


class JobError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def enqueue(db, document_id, settings, key=None):
    if key is not None:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
            raise JobError(422, "invalid_idempotency_key", "Idempotency key is invalid")
        # Serialize a key even when its request row does not exist yet. Hash
        # collisions merely serialize unrelated keys; exact strings remain authoritative.
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
        db.execute(select(func.pg_advisory_xact_lock(lock_id)))
        original = db.get(JobRequest, key)
        if original is not None:
            if original.document_id != document_id:
                raise JobError(409, "idempotency_conflict", "Key belongs to another document")
            return db.get(ProcessingJob, original.job_id)
    document = db.scalar(
        select(Document).where(Document.document_id == document_id).with_for_update()
    )
    if document is None:
        raise JobError(404, "document_not_found", "Document not found")
    claim = db.scalar(select(Claim).where(Claim.claim_id == document.claim_id).with_for_update())
    active = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.document_id == document_id, ProcessingJob.state.in_(ACTIVE)
        )
    )
    if active is not None:
        if (
            document.document_state not in {"QUEUED", "PROCESSING"}
            or claim.current_state != "PROCESSING"
        ):
            raise JobError(409, "processing_conflict", "Resource states are inconsistent")
        job = active
    else:
        if (document.document_state, claim.current_state) not in {
            ("UPLOADED", "RECEIVED"),
            ("FAILED", "FAILED"),
        }:
            raise JobError(
                409, "processing_conflict", "Document cannot be queued in its current state"
            )
        job = ProcessingJob(
            document_id=document_id,
            max_attempts=settings.job_max_attempts,
            idempotency_key=key,
            state="QUEUED",
            attempts=0,
        )
        db.add(job)
        db.flush()
        document.document_state = "QUEUED"
        claim.current_state = "PROCESSING"
        claim.version += 1
    if key is not None:
        db.add(JobRequest(key=key, job_id=job.job_id, document_id=document_id))
    db.flush()
    return job
