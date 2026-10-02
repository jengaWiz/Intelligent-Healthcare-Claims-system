"""Lease ownership, bounded retries, and recovery use PostgreSQL database time."""

import math
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update

from models import Claim, Document, ProcessingJob
from services.extraction_service import ProcessingConflict


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    owner: UUID
    document_path: str
    attempts: int


def locked_resources(db, job):
    document = db.scalar(
        select(Document).where(Document.document_id == job.document_id).with_for_update()
    )
    claim = db.scalar(select(Claim).where(Claim.claim_id == document.claim_id).with_for_update())
    return document, claim


def terminal_failure(job, document, claim, now, code):
    job.state = "FAILED"
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.next_attempt_at = None
    job.error_code = code
    job.error_message = "Processing could not be completed"
    document.document_state = "FAILED"
    claim.current_state = "FAILED"
    claim.version += 1


def acquire(db, settings):
    # NO KEY UPDATE is compatible with request/result foreign-key checks while
    # still excluding other workers. Never lock job IDs before taking an alias key.
    job = db.scalar(
        select(ProcessingJob)
        .where(
            or_(
                ProcessingJob.state == "QUEUED",
                and_(
                    ProcessingJob.state == "RETRY_WAIT",
                    ProcessingJob.next_attempt_at <= func.clock_timestamp(),
                ),
                and_(
                    ProcessingJob.state == "RUNNING",
                    ProcessingJob.lease_expires_at <= func.clock_timestamp(),
                ),
            )
        )
        .order_by(ProcessingJob.created_at, ProcessingJob.job_id)
        .limit(1)
        .with_for_update(skip_locked=True, key_share=True)
    )
    if job is None:
        return None
    document, claim = locked_resources(db, job)
    now = db.scalar(select(func.clock_timestamp()))
    if claim.current_state != "PROCESSING" or document.document_state not in {
        "QUEUED",
        "PROCESSING",
    }:
        raise ProcessingConflict("Queued resource states are inconsistent")
    if job.attempts >= job.max_attempts:
        terminal_failure(job, document, claim, now, "attempts_exhausted")
        db.flush()
        return None
    job.attempts += 1
    job.state = "RUNNING"
    job.lease_owner = uuid4()  # New token for every attempt; process IDs are insufficient.
    job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
    job.started_at = job.started_at or now
    job.next_attempt_at = None
    document.document_state = "PROCESSING"
    db.flush()
    return Lease(job.job_id, job.lease_owner, document.storage_path, job.attempts)


def heartbeat(db, lease, settings):
    result = db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.job_id == lease.job_id,
            ProcessingJob.state == "RUNNING",
            ProcessingJob.lease_owner == lease.owner,
            ProcessingJob.lease_expires_at > func.clock_timestamp(),
        )
        .values(
            lease_expires_at=func.clock_timestamp() + timedelta(seconds=settings.job_lease_seconds)
        )
    )
    return result.rowcount == 1


def fail_attempt(db, lease, failure):
    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.job_id == lease.job_id,
            ProcessingJob.state == "RUNNING",
            ProcessingJob.lease_owner == lease.owner,
            ProcessingJob.lease_expires_at > func.clock_timestamp(),
        )
        .with_for_update(key_share=True)
    )
    if job is None:
        raise ProcessingConflict("Job lease is not active or owned")
    document, claim = locked_resources(db, job)
    now = db.scalar(select(func.clock_timestamp()))
    if job.lease_expires_at <= now:
        raise ProcessingConflict("Job lease expired while acquiring locks")
    if document.document_state != "PROCESSING" or claim.current_state != "PROCESSING":
        raise ProcessingConflict("Running resource states are inconsistent")
    if failure.retryable and job.attempts < job.max_attempts:
        delay = min(60, 2 ** min(job.attempts, 6))
        if failure.retry_after is not None and math.isfinite(failure.retry_after):
            delay = max(delay, min(60, max(0, failure.retry_after)))
        job.state = "RETRY_WAIT"
        job.next_attempt_at = now + timedelta(seconds=delay)
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_code = failure.code.value
        job.error_message = "Processing will be retried"
        document.document_state = "QUEUED"
    else:
        terminal_failure(job, document, claim, now, failure.code.value)
    db.flush()
