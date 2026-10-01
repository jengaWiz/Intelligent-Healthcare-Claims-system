# M1 persistence

Run from the repository root after `uv sync --locked`. Set `DATABASE_URL` to a
PostgreSQL database using `postgresql+psycopg://` and your own credentials.

```bash
uv run --locked alembic upgrade head
uv run --locked alembic check
```

The initial migration creates claims, documents, processing jobs, extraction
results, validation outcomes, and reviews. It is intended for an empty prototype
database. It does not automatically adopt or repair manually created legacy
schemas; back up and assess any existing database separately before migration.

M1 allows one document per claim and one final extraction result per document.
A partial unique index allows one active job per document; failed historical
jobs remain so a new retry can be created. Foreign keys cascade prototype
records when a claim is deleted. File deletion is a separate storage concern
implemented by the upload/retention ticket. Review revisions are unique per
claim/version. Check constraints bound states, scores, attempts, and leases.

Services flush mutations rather than committing them. API/worker callers must
own a `with session.begin():` transaction so exceptions roll back all database
changes. Never hold a transaction while invoking a provider. SQLAlchemy models
register together through `models`; Alembic loads the same metadata.

The legacy synchronous extraction service is not compatible with the complete
M1 result contract yet. Pipeline normalization and durable jobs are separate
issues #8/#9. Do not expose that handler as a completed M1 API.

## Integration tests

Use only a dedicated test database. Migrate it first and set `TEST_DATABASE_URL`
to its URL; then run `uv run --locked pytest -m integration`. Ordinary unit runs
skip database tests if this variable is absent. Each integration test uses an
outer rollback with nested session savepoints to avoid persisting fixtures.

## Migration rehearsal

On an empty disposable database only, run upgrade, check, downgrade, and upgrade
again, then run integration tests. `downgrade base` drops every M1 table and its
data. Deployment rollback must normally restore the previous compatible image;
back up the database before any destructive schema rollback and document the
specific release migration plan. Database and upload snapshots must correspond.
