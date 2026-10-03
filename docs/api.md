# Claim API

The API implements claim creation/lookup, bounded document uploads, document metadata,
results, review actions/history, browser sessions, and health probes. Extraction
enqueues durable jobs with authenticated polling; see the [worker guide](jobs.md).
Uploads use the foundation schema; durable enqueue requires the job request-key migration.

## Start locally

```bash
uv sync --locked
cp .env.example .env
# Edit .env: DATABASE_URL uses postgresql+psycopg:// with your local credentials.
# Set API_AUTH_TOKEN to a server-generated secret; do not commit it.
uv run --locked alembic upgrade head
uv run --locked uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Open `http://127.0.0.1:8000/docs` for the API explorer. Use its Authorize button to
supply the configured bearer token. `POST /claims` accepts `{}` or
`{"source_system":"synthetic-demo"}` and returns 201 with a `Location` header.
`GET` that location retrieves the committed claim. Source strings are trimmed,
bounded to 100 characters, and may be null; unknown input fields are rejected.

The API projection contains ID, state, version, source system, and UTC timestamps;
ORM relationships, storage locations, database configuration, and provider keys
are excluded. Errors contain only a safe code/message and generated request ID,
which also appears in `X-Request-ID`. HTTP 401 includes a bearer challenge.

## Health and resource boundaries

`GET /health/live` is public and initializes no database or provider client.
`GET /health/ready` requires authentication and probes the database plus writable
upload storage. It returns 503 when either is unavailable. It does not test
provider access or semantic completeness. Controlled compose migration gates
ensure the schema is upgraded before startup. Public liveness/OpenAPI contain no secrets.

`DATABASE_TIMEOUT_SECONDS` (default 3, range 1–10) bounds connection establishment,
pool acquisition, and SQL statements individually. These are per-operation limits,
not a single wall-clock deadline across all readiness steps. Each app instance
owns its lazily initialized engine, disposes it at shutdown, and does not share
ORM sessions across requests. POST commits its transaction before returning 201.

Browser sessions and operator bearer requests use separate workspaces. Every
claim/document/job/result/review lookup checks ownership and returns 404 for other
workspaces. Browser mutations require exact PUBLIC_ORIGIN and X-CSRF-Token.
See [access handling](access.md) and [the local Docker setup](deployment.md).

## Verification

## Explainable risk review

Results include nullable `risk` and `risk_acknowledgment`. Null means not assessed;
INSUFFICIENT_DATA means an assessment ran without sufficient evidence. Risk is
independent of claim state; a READY/HIGH claim can be acknowledged without
changing its data or level. Internal fingerprints and peer identifiers are omitted.

- `GET /claims/{id}/risk`: bounded assessment history, limit 1–100 (default 20), offset >= 0.
- `POST /claims/{id}/risk/refresh`: `{ "expected_version": 3 }`; returns the current assessment.
- `POST /claims/{id}/risk/acknowledgments`: expected_version, current assessment_id and reason (1–2000 chars); actor comes from authentication.

Cookie mutations require exact Origin and CSRF. Cross-workspace reads/mutations
return 404; stale data/assessment IDs return 409. Acknowledgment is immutable and
does not transfer to a new assessment. See [policy and error contracts](risk.md).

## HTTP verification

Unit HTTP tests use an isolated SQLite claim table; PostgreSQL HTTP integration
tests use the migrated `TEST_DATABASE_URL` database with per-test rollback.
They verify POST persistence across sessions, GET/404/422 behavior, auth ordering,
redaction, transaction rollback, readiness, and OpenAPI response contracts.
Use the commands in [contributing](../CONTRIBUTING.md) for all checks.

## Document upload

`POST /claims/{claim_id}/documents` accepts one multipart `file` and requires the
bearer token. The claim must exist, be RECEIVED, and have no existing document.
Successful uploads return 201 with document metadata and a `Location` header for
`GET /documents/{document_id}`. Concurrent uploads serialize on the claim row;
only one can succeed. No OCR or LLM call runs during upload.

Accepted MIME types are `application/pdf`, `image/jpeg`, and `image/png` with
matching basic file signatures. This identifies the format; it does not validate
a complete document or scan its contents. Empty files return 422, unsupported or
mismatched formats 415, missing claims 404, and conflicting uploads 409.
`MAX_UPLOAD_BYTES` bounds the file; the multipart request has an additional fixed
64 KiB framing allowance. Both declared-length and chunked requests are bounded
before the parser can spool an unlimited body. Oversized requests return 413.

The display filename cannot select a storage path. Traversal names are rejected;
Windows paths normalized by the multipart parser become display basenames.
Storage uses generated names and private file permissions under `UPLOAD_DIR`.
Metadata contains byte size and SHA-256, never the physical storage path.
See [upload storage](uploads.md) for persistence, cleanup, and retention behavior.

## Asynchronous extraction

POST `/documents/{document_id}/extract` with an optional `Idempotency-Key` commits
a job and returns 202, its `/jobs/{id}` Location, and Retry-After: 2. GET that
location with the bearer token for safe state/error metadata. The API runs no
providers; start the [separate worker](jobs.md) to process the queue.

## Results and review

GET `/claims` lists owned claims with bounded limit/offset pagination. GET
`/claims/{id}/results` returns typed state/job, original extraction, current fields
and validation, and ordered audit history. GET `/reviews` lists owned review-required
claims. POST `/claims/{id}/reviews` accepts expected_version, decision, reason and
(for corrections only) bounded corrected fields. GET `/claims/{id}/reviews` returns
actor/time/reason/before-after revisions. See [review contracts](review.md).
