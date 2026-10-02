# Local Docker deployment

The user selected **local Docker only, no hosting cost**. This supersedes the
original paid staging/HTTPS provisioning task. The demo binds only to loopback;
there is no public recruiter URL, cloud account requirement, or hosting bill.
Azure/LLM evaluation is separate and opt-in. No production data belongs here.

## Fresh setup

```bash
uv run --locked python -m scripts.init_demo
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d --wait
```

Open http://127.0.0.1:8000/demo and use DEMO_PASSWORD from the private `.env.docker`.
The initializer preserves existing credentials and creates new files with mode 0600.
Do not commit it, paste it into issue logs, or bake it into images. Compose injects
it at runtime. Its local-only insecure cookie flag must never be reused on public HTTP.
Use the labeled samples and [browser walkthrough](interface.md).

The pinned-base Python image uses locked dependencies and UID/GID 10001, a
read-only root, dropped capabilities, temporary scratch storage, and a persistent
upload volume. Separate API and worker containers share `/data/uploads`.
PostgreSQL 16 has a dedicated persistent volume and no published port. Startup
waits for database health, runs a one-off migration, then coordinated upload
reconciliation before API/worker start. Readiness requires authenticated database
access and a writable upload-volume probe; Docker performs this probe without printing the token. Ordinary `down`
retains data. `down --volumes` destroys it and is for an explicit synthetic reset only.

## Controlled releases and image rollback

Stop API/worker before schema changes and retain their current image ID with
`docker compose --env-file .env.docker images`. Create a paired backup first.
Build/tag the candidate, run the `migrate` and `reconcile` one-off services, then
start API/worker and verify readiness and a synthetic flow. Record the image ID,
commit, migration head and previous compatible image in release notes.

To redeploy a retained **schema-compatible** image, export CLAIMS_IMAGE to its
immutable image ID and run compose `up -d --no-build --force-recreate api worker`.
Do not blindly downgrade migrations. If a schema-incompatible release must be
rolled back, stop writes and restore the paired backup into a fresh compose
project using the matching previous image, then verify it before switching access.
The local smoke rehearses a retained-image redeploy of this same release; it is
not evidence that older pre-session binaries are compatible with the new schema.
Migration downgrade limitations are in [jobs.md](jobs.md) and [access.md](access.md).

## Paired backup and restore

```bash
uv run --locked python -m scripts.backup_demo backup /private/tmp/claims-backup-unique
# Restore uses a NEW project; stop the old API/worker first to free the port.
uv run --locked python -m scripts.backup_demo restore /private/tmp/claims-backup-unique --project claims-restored
```

Backup stops API/worker, creates a custom-format PostgreSQL dump plus generated-file
archive and checksums, then starts services again. Store the private directory
outside the repo and preserve both files together. Restore verifies checksums and
refuses an existing compose project; uploads must land on a fresh volume.
The archive helper rejects paths, links, unsupported names, oversized files, and
existing destinations. PostgreSQL restore must use a compatible database major
version and application schema. Failed/partial restores need a new project/volume;
do not serve a partially restored stack.

Rotate DEMO_PASSWORD/API_AUTH_TOKEN in `.env.docker` and recreate API/worker;
revoke browser sessions explicitly when changing access. POSTGRES_PASSWORD must
also be changed in the actual database using an authenticated administrator
session before updating runtime credentials; changing an env file alone does not
rotate an existing volume's password. No credentials are echoed by these scripts.

## Disposable verification

```bash
uv run --locked python -m scripts.check_compose
```

This creates random `claims-smoke-*` projects on loopback port 18047, checks real
HTTP upload/results/review/failure/retry, restarts API/worker around a queued job,
verifies every uploaded byte hash, restores a paired backup to another fresh
project, and redeploys a retained image. It removes only its own disposable volumes.
The running `claims-demo` project remains intact. Actual evidence is recorded in
`docs/verification/compose.json`; fixture checks make no live-provider accuracy claim.
