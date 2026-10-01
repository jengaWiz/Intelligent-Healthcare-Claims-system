# ADR 001: PostgreSQL-backed jobs and a small synchronous worker

Status: proposed for review in issue #2; accepted when its PR merges.

## Context

M1 already needs PostgreSQL for claims and results. Request-thread extraction
blocks uploads, and an in-memory/background task can disappear during a restart.
The demo needs durable retries without a second queue service or orchestration framework.

## Decision

Keep one synchronous worker process alongside the FastAPI process. Persist job
state, attempts, deadlines, idempotency keys, lease owner, and lease expiry in
PostgreSQL. Claim work using short transactions and SKIP LOCKED; invoke providers
outside transactions; use a separate heartbeat session. Persist completion and
claim/document updates atomically after checking lease ownership. See the
[contract](../m1-contracts.md) for transitions and crash recovery.

Use Python 3.12, Pydantic 2 with pydantic-settings, SQLAlchemy 2 with psycopg 3,
Alembic, FastAPI, LangGraph/LangChain adapters, and Azure Document Intelligence.
The setup ticket pins direct releases in pyproject.toml and commits uv.lock as
the authoritative exact transitive dependency set. The initial resolved set uses
Pydantic 2.13.5, SQLAlchemy 2.0.54, Azure Document Intelligence 1.0.2,
LangChain Google 4.4.0/OpenAI 1.6.7, and LangGraph 1.2.12. Compatibility is verified
by credential-free tests; live account/model access remains an opt-in check. Use provider-
configurable models rather than the existing stale hardcoded Gemini default.
Application code owns gates, retries, routing, storage, and state; agents only
produce bounded typed data. A provider key is required only when its integration
starts, not when importing schemas/configuration or collecting unit tests.

## Alternatives

FastAPI BackgroundTasks/in-memory queues are simple but cannot satisfy durable
restart recovery. Celery/Redis adds another service and lifecycle to a small
demo. Revisit a dedicated queue if volume, scheduling, or multi-region requirements
outgrow PostgreSQL polling; it is unnecessary for M1.

## Consequences

The worker must implement lease ownership, retry limits, and recovery tests.
PostgreSQL availability controls both persistence and queue availability. Polling
must be bounded (one-second idle wait by default). Providers can charge twice if
a worker crashes after a successful external call but before result commit.
No exactly-once external-call guarantee is claimed. Backup and restore must
include job state and uploads as well as claim data.

## Hosting candidates (no provisioning decision yet)

| Candidate | Benefits | Decision checks |
| --- | --- | --- |
| Container PaaS with managed PostgreSQL | Small operational footprint | Worker support, durable disk/object storage, TLS, secrets, price and sleep behavior |
| Single container-capable VM | API/worker/storage control | Backups, TLS termination, patching, monitoring, cost and restore ownership |
| Cloud container service + managed PostgreSQL | Clear API/worker separation | Persistent uploads, network/secrets configuration, idle cost and deployment complexity |

Issue #14 selects a target against budget, credentials, durable uploads, health
checks, migration release steps, rollback, and database backup needs. Serverless
request-only hosting is unsuitable without a separate durable worker. Containers
and local compose are the portable baseline; no cloud purchase is implied.
