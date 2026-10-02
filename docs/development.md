# Development setup

Use Python 3.12 and uv 0.7.17 or newer. Direct and transitive dependencies are
committed in `pyproject.toml` and `uv.lock`; ordinary checks need no provider keys.

```bash
uv sync --locked
cp .env.example .env
uv run --locked pytest tests/test_settings.py -q
```

Configuration is loaded by `config.settings.Settings` from environment variables
and an optional local `.env`; environment values win. Empty optional credentials
are treated as unset. Pure imports do not connect to services, construct provider
clients, or create upload directories. Tests can pass `Settings(_env_file=None)`
and inject settings into extraction/validation agents.

Before accessing PostgreSQL, set `DATABASE_URL` with the explicit driver prefix
`postgresql+psycopg://` and your own local credentials. Migrations are available; the [API guide](api.md) describes startup and the
implemented claim, upload, metadata, and health routes. The complete extraction workflow remains unfinished.

Before calling Azure, set its HTTPS endpoint and key. The configurable document
model defaults to `prebuilt-layout`; provider compatibility/live behavior is
verified by ticket #7. Before calling an LLM, set `LLM_PROVIDER`, `LLM_MODEL`, and
only that provider's key. The project deliberately has no guessed model default.
Client constructors disable their internal retry loops; the durable worker ticket
owns overall retries. Timeout, lease, heartbeat, upload size, confidence threshold,
origins, and future auth settings have validated limits.

`API_AUTH_TOKEN` protects the current API/readiness routes with a bearer guard.
Full reviewer/session handling remains in the authentication ticket. Secrets
and uploads are ignored by git; migrations and `alembic.ini` must remain tracked.

Update dependencies with uv, commit the new exact pins and lockfile, and rerun
checks. Setup CI verifies locked installation and configuration boundaries. The legacy schema import and provider tests are repaired here so all current
unit tests pass. Expanded CI runs lint, format, documentation, all unit tests, and PostgreSQL
integration/migration checks. See [contributing](../CONTRIBUTING.md) and
[database setup](database.md) for the full commands.
