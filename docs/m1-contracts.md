# M1 workflow contract

Status: implemented local-demo contract. Final API/review/access behavior is also
documented in [api.md](api.md), [review.md](review.md), and [access.md](access.md).
Tracked by [issue #2](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/2)
and [M1](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/milestone/1).
See [ADR 001](decisions/001-durable-processing.md) for runtime and deployment choices.

## Scope and vocabulary

Process synthetic documents into reviewable data. `READY` means extraction and
validation passed the data-quality gates; it never authorizes insurance coverage
or payment. M1 processes one document per claim. Multiple-document reconciliation,
payer integration, medical coding, and real patient data are outside this milestone.

IDs are UUIDs, timestamps are UTC ISO 8601, dates are ISO calendar dates, and money
is a decimal string with currency `USD`. Unknown fields are `null`, never guessed.
Confidence must be finite and within [0, 1]. It is model-reported extraction
confidence, not a calibrated accuracy measurement. Server-generated provenance
records model, provider, prompt/schema version, and document/job IDs.

## HTTP contract

All claim/document/job/review routes require the demo's server-managed session or
configured API bearer token. Record authorization is checked for every request;
Each browser session has an isolated workspace; the operator token owns a
separate workspace. Public
liveness contains no configuration, data, or dependency details. Readiness requires
authentication. Use explicit browser origins.

| Method and path | Request | Response and errors |
| --- | --- | --- |
| `POST /claims` | `{ "source_system": "synthetic-demo" }` (optional bounded string) | 201 claim; `Location: /claims/{id}` |
| `GET /claims/{claim_id}` | UUID | 200 claim, or 404 |
| `POST /claims/{claim_id}/documents` | Multipart `file`: PDF/JPEG/PNG | 201 document; 404 claim, 409 second document, 413 size, 415 unsupported content |
| `GET /documents/{document_id}` | UUID | 200 document metadata; never filesystem paths |
| `POST /documents/{document_id}/extract` | No body, optional `Idempotency-Key` | 202 job with `Location: /jobs/{id}` and `Retry-After: 2`; 409 ineligible state |
| `GET /jobs/{job_id}` | UUID | 200 job; 404; poll every 2 seconds, stop on terminal state |
| `GET /claims/{claim_id}/results` | UUID | 200 claim/job/original/current/audit projection; extraction/current are null before success |
| `GET /claims` | `limit` (1–100), nonnegative `offset` | 200 owned claim list |
| `GET /reviews` | `limit` (1–100), nonnegative `offset` | 200 owned review-required claim list |
| `POST /claims/{claim_id}/reviews` | Decision, expected version, reason, optional corrected fields | 200 typed updated results with audit; 409 stale version/state |
| `GET /claims/{claim_id}/reviews` | UUID | 200 ordered audit history |
| `GET /health/live` | None | 200 `{ "status": "ok" }` |
| `GET /health/ready` | Infrastructure authorization | 200 ready or 503 unavailable; bounded DB/storage check |

Invalid UUIDs/body fields return 422, missing/invalid authentication returns 401,
other workspaces return 404 without confirming record existence; CSRF/origin failures return 403. Error bodies use
`{ "code": "document_not_found", "message": "Document not found", "request_id": "..." }`.
Never echo credentials, document text, raw provider errors, or storage paths.
An unavailable processing provider fails a job; it does not turn polling into an
HTTP 500. The UI uses same-origin, HTTP-only sessions; provider/server tokens must
not enter browser bundles. Cookie mutations require CSRF protection.

## Resource fields

- Claim: `claim_id`, `state`, `version` (integer starting at 1), `source_system`,
  `created_at`, `updated_at`. Increment version on every state or review mutation.
- Document: `document_id`, `claim_id`, `file_name` (display only), `mime_type`,
  `byte_size`, `sha256`, `state`, `created_at`. Store files under generated names.
- Job: `job_id`, `document_id`, `state`, `attempts`, `max_attempts`, `created_at`,
  `started_at`, `completed_at`, `next_attempt_at`, `error` (safe code/message or null).
- Results projection: `claim`, latest `job` (or null), `extraction` (or null),
  `current` (or null), ordered `reviews`. Extraction contains ID, engine/version,
  original normalized data, confidence, reasoning, original outcome, provenance,
  and timestamp. Current contains `data`, `validation`, and `human_reviewed`.
  Original evidence is immutable; human review creates a new current/audit snapshot.
- Validation: `is_valid`, `validation_score` [0,1], `issues` with severity
  (`critical`, `warning`, `info`), field, type, description, suggested fix;
  `recommendations`, `semantic_status` (`completed`, `unavailable`).
- Review request: `decision` (`approve`, `correct`, `reject`), `expected_version`,
  nonempty bounded `reason`; `corrections` requires the complete bounded correction object containing patient name/DOB,
  provider name, service date, and amount. Corrections are normalized and revalidated.
  Actor identity comes from authentication, never caller-supplied body fields.
- Review response/history: `review_id`, `actor_id`, `decision`, reason,
  `previous_version`, `new_version`, `before_data`, `after_data`, `created_at`.
  The claim ID is provided by the enclosing result/route.

Illustrative payloads are in [examples/m1-responses.json](examples/m1-responses.json).
The independent review request example applies only to a REVIEW_REQUIRED claim.
Clients must tolerate absent optional metadata; unknown input keys are rejected.

## State machines

| Resource | From | To | Trigger |
| --- | --- | --- | --- |
| Claim | RECEIVED | PROCESSING | Document job queued atomically |
| Claim | PROCESSING | READY | Data gates pass |
| Claim | PROCESSING | REVIEW_REQUIRED | Extraction succeeds but any review gate fails |
| Claim | PROCESSING | FAILED | Permanent/exhausted infrastructure, OCR, or parsing failure |
| Claim | FAILED | PROCESSING | Explicit authorized retry queues a new job |
| Claim | REVIEW_REQUIRED | READY | Reviewer approves/corrects after revalidation |
| Claim | REVIEW_REQUIRED | REJECTED | Reviewer rejects data quality |
| Document | UPLOADED | QUEUED | Enqueue |
| Document | QUEUED | PROCESSING | Worker claims job |
| Document | PROCESSING | EXTRACTED | Normalized result persisted, including review-required result |
| Document | PROCESSING | QUEUED | Transient retry |
| Document | PROCESSING | PROCESSING | Expired attempt replaced under a fresh lease |
| Document | PROCESSING | FAILED | Permanent/exhausted failure |
| Document | FAILED | QUEUED | Explicit retry |
| Job | QUEUED | RUNNING | Lease acquired |
| Job | RUNNING | SUCCEEDED | Result and states committed together |
| Job | RUNNING | RETRY_WAIT | Retryable provider error before attempt limit |
| Job | RETRY_WAIT | RUNNING | Due retry obtains lease |
| Job | RUNNING | RUNNING | Expired lease replaced with fresh owner/attempt |
| Job | RUNNING | FAILED | Permanent error or attempt limit reached |

All unspecified transitions return conflict without side effects. `SUCCEEDED`
means the pipeline persisted a result, which may require review. While a job is
waiting for retry, claim remains PROCESSING and document is QUEUED. READY and
REJECTED are terminal for M1. Retry an exhausted/failed job by creating a new job;
retain the old failure and history. Validation/review work is not an extraction
retry. Reviewer approval requires no critical deterministic issues; semantic
unavailability or low confidence can be resolved only by an explicit audited
human attestation. Corrections that still contain critical issues return 422 and
leave the claim in REVIEW_REQUIRED.

## Gates and failure behavior

| Scenario | Job | Claim | Required evidence/action |
| --- | --- | --- | --- |
| Complete valid fields; confidence >= threshold; semantic check completed with no issues | SUCCEEDED | READY | Persist normalized data and validation |
| Confidence below threshold | SUCCEEDED | REVIEW_REQUIRED | Show confidence/reason; human review |
| Missing patient name, service date, amount; zero/negative amount; future service date; DOB >= service date | SUCCEEDED | REVIEW_REQUIRED | Critical field issues; correct or reject |
| Invalid/unparseable date/amount | SUCCEEDED | REVIEW_REQUIRED | Keep raw provenance and mark normalized value missing/invalid |
| Noncritical warnings or semantic issues | SUCCEEDED | REVIEW_REQUIRED | Show warnings, require attestation/correction |
| Semantic provider unavailable | SUCCEEDED | REVIEW_REQUIRED | `semantic_status=unavailable`; never clean approval |
| OCR/extraction unavailable or malformed structured output | RETRY_WAIT or FAILED | PROCESSING or FAILED | Bounded transient retry; permanent parse/config failure fails immediately |
| Explicit retry after permanent/exhausted failure | New QUEUED job | PROCESSING | Authorized action and fresh job ID; preserve prior failure |

Default extraction threshold is 0.8, max job attempts 3, provider request timeout
30 seconds, polling interval 2 seconds, per-file upload limit 10 MiB. Limits are
validated configuration, not magic values spread through application code.

## Concurrency, retries, and durability

Enqueue transaction locks the document row, validates state, creates the job, and
sets claim/document states. A partial unique index permits only one active job
(QUEUED/RUNNING/RETRY_WAIT) per document. Duplicate concurrent requests return the
existing active job with 202. Reusing a supplied idempotency key returns its
original job; reuse against a different document returns 409. After success,
a fresh enqueue returns 409; an already accepted key still returns its original
job with 202. No duplicate result is created.

Workers use PostgreSQL row locking (`FOR NO KEY UPDATE SKIP LOCKED`), persisted leases,
heartbeat/owner tokens, and bounded retries. Never hold a DB transaction open
while calling OCR/LLM providers. Commit results only if the worker still owns the
lease; an expired/stale worker cannot overwrite the winning result. A unique
result per job makes completion repeatable. Recovery increments attempts, and
marks exhausted jobs FAILED, rather than allowing endless crash/reclaim loops.
Default lease is 120 seconds with heartbeat every 20 seconds; provider calls are
bounded below the lease and heartbeat uses a separate session. Retrying external
calls may incur duplicate provider charges; result persistence remains deduplicated.
Use capped exponential backoff (2, 4 seconds) for the two default retries; honor
bounded Retry-After on 429. Configuration and parsing errors are permanent.

Each reviewer action locks/compares the claim version and persists decision,
correction, new state, and audit event in one transaction. A stale version returns
409. No mutable ORM session is shared between request, job, and heartbeat.

## Delivery and verification

Implement through the [master checklist](https://github.com/jengaWiz/Intelligent-Healthcare-Claims-system/issues/16).
Feature branches and reviewed PRs target `ayaan`. Tests use fakes and synthetic
fixtures; live provider smoke checks are explicitly opt-in. Integration tests
use PostgreSQL to exercise locking, migrations, constraints, and rollback.
The selected local Docker deployment uses API, worker, PostgreSQL, durable uploads,
server-managed secrets, and loopback-only HTTP. Paid hosting/TLS provisioning was
removed from this release by the user’s explicit local-only choice. Public hosting
would require a new budget/account decision and HTTPS configuration.
