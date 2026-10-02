# Durable processing jobs and worker

`POST /documents/{document_id}/extract` requires the API bearer token. It commits a
queued job and claim/document state changes before returning 202, a `Location`
header for `/jobs/{job_id}`, and `Retry-After: 2`. The HTTP request runs no provider
work. Poll the authenticated GET route until SUCCEEDED or FAILED. SUCCEEDED means
a normalized result was persisted, possibly with REVIEW_REQUIRED; it is not an
insurance decision. Result/review endpoints remain ticket #10.

## Duplicate requests and retries

M1 permits one active job (QUEUED/RUNNING/RETRY_WAIT) per document. Concurrent
submissions return the same job. Optional `Idempotency-Key` values contain 1–128
ASCII letters, digits, or `._:-`. Every accepted key stays bound to its original
job, including additional keys accepted while a job is active. Reusing a key
against another document returns 409. Replaying a terminal key returns its original
job; explicitly retry a FAILED document using a fresh key or no key. A successful
EXTRACTED document cannot be extracted again. Both missing documents and invalid
states produce safe errors without changing resources.

A new job changes RECEIVED/UPLOADED or FAILED/FAILED to PROCESSING/QUEUED and
increments the claim version. Acquisition changes the document to PROCESSING.
Transient OCR/extraction failures change the job to RETRY_WAIT and document to
QUEUED; claim stays PROCESSING. Permanent/exhausted failures atomically mark job,
document, and claim FAILED. Successful completion atomically persists result,
validation, provenance, and all completion states through the #8 processing service.

`job_requests` retains key-to-document/job mappings, enforced by a composite
foreign key. Transaction-scoped advisory locks serialize identical new keys;
exact stored strings determine identity even if lock hashes collide. Document
locks and the active-job unique index enforce one active job. Workers acquire
job rows with `FOR NO KEY UPDATE SKIP LOCKED`, compatible with request/result
foreign-key checks. See [PostgreSQL advisory lock documentation](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS).

## Run independently

Apply migrations first. Start API and worker as separate processes sharing the
same PostgreSQL database and persistent `UPLOAD_DIR` at the same absolute path.
Only the worker needs Azure and selected LLM credentials for live processing.
Provider failures, including missing configuration, become safe job failures.

```bash
uv run --locked alembic upgrade head
uv run --locked uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000
# In another terminal with the same configuration:
uv run --locked python -m worker
# Handle at most one eligible job (or an exhausted recovery), then exit:
uv run --locked python -m worker --once
```

`--once` success means the worker handled a tick without a database/runtime error;
inspect the job state to determine processing success. Idle workers wait for
`WORKER_POLL_SECONDS` and can run concurrently. The worker opens separate short
sessions for acquisition, heartbeats, and completion. No request-scoped session
survives its HTTP response, and no transaction remains open during provider work.
Only files resolving directly inside UPLOAD_DIR can be processed.

Each attempt gets a new UUID ownership token and a database-time lease. A separate
heartbeat session extends an unexpired owned lease every JOB_HEARTBEAT_SECONDS.
Lost/unconfirmed ownership prevents completion; persistence checks ownership again.
Expired RUNNING jobs are reclaimed on a later worker tick. Every acquisition or
crash recovery increments attempts. A crashed final attempt becomes FAILED when
its expired lease is examined; an old worker cannot overwrite its replacement.

Job attempt limits are captured from JOB_MAX_ATTEMPTS when enqueued (default 3).
Retries use exponential delays of 2, 4 seconds for default attempts, capped at 60;
numeric provider Retry-After can extend a delay up to 60 seconds. SDK retry loops
remain disabled. No exactly-once provider call guarantee is claimed: a process
crash after a provider response can cause a second billable call. Result/job IDs,
unique constraints, and leases prevent duplicate final results.

SIGINT/SIGTERM stop new acquisitions after current work completes. Forced process
termination relies on lease expiry/recovery. Database and provider timeouts are
connection/read/statement limits; they are not OS-enforced elapsed-time kills.
See [provider boundaries](providers.md). Database unavailability produces safe
worker log codes and polling delays; a RUNNING lease is left recoverable rather
than incorrectly committing a provider failure. Logs contain job IDs, not content,
filenames, keys, or raw exception text. Failed attempt error messages are fixed
safe projections; job responses omit leases, storage paths, and idempotency keys.

## Migration and verification

Migration `a04b9c2d310f` creates job_requests and backfills existing first keys from
processing_jobs. Stop API enqueue traffic and workers before release migrations
or rollback. Downgrade drops the additional alias mappings; the original first
key remains in processing_jobs. Restore a database backup if those mappings must
survive rollback. New binaries require the migration before startup. Document
cleanup remains the separate outstanding #6 reconciliation work.

Integration tests use a dedicated migrated PostgreSQL database, fake processors,
and fixed synthetic uploads. They cover concurrent enqueue, cross-document key
conflicts, authenticated 202/polling, duplicate aliases, bounded retries, exhausted
crash loops, stale completion, live heartbeats, and actual subprocess crash/restart.
A subprocess commits a lease and exits abruptly; a fresh subprocess recovers the
expired job and persists exactly one result. No live OCR/LLM calls run in CI.
