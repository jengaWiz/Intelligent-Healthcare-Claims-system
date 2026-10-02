# Claim API

The API implements claim creation/lookup, bounded document uploads, document metadata,
and health probes. Extraction remains an explicit 501 placeholder pending ticket #9.
No additional schema migration is required for uploads.

## Start locally

```bash
uv sync --locked
cp .env.example .env
# Edit .env: DATABASE_URL uses postgresql+psycopg:// with your local credentials.
# Set API_AUTH_TOKEN to a server-generated secret; do not commit it.
uv run --locked alembic upgrade head
uv run --locked uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000
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
`GET /health/ready` requires the token and runs `SELECT 1`. It returns 503 if the
database/configuration is unavailable. It does not test provider access, data
completeness, migrations, or upload storage yet. Public liveness and OpenAPI contain
no secrets. Claim routes and readiness return 503 until a token is configured.

`DATABASE_TIMEOUT_SECONDS` (default 3, range 1–10) bounds connection establishment,
pool acquisition, and SQL statements individually. These are per-operation limits,
not a single wall-clock deadline across all readiness steps. Each app instance
owns its lazily initialized engine, disposes it at shutdown, and does not share
ORM sessions across requests. POST commits its transaction before returning 201.

This bearer-token guard is the minimum fail-closed boundary for the local API.
Reviewer identities, browser sessions/CSRF, record access rules, automated retention, and
safe operational logging remain in ticket #11. Keep this prototype local until
that work and deployment verification are complete. Provider credentials are not
needed to create/read claims or use health probes.

## Verification

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
