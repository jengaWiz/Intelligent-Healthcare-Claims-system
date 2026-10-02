# Upload storage and verification

Set `UPLOAD_DIR` to an absolute directory on persistent storage in containers.
Temporary files and completed uploads share this root, so promotion is atomic.
Files are flushed and synced before the metadata transaction commits. The API
rechecks and locks the claim after receiving the body, avoiding long database
transactions during slow uploads.

Ordinary storage, flush, and confirmed rollback failures remove staged/completed
files. A lost commit acknowledgement is checked using a fresh database session:
a confirmed document returns success and retains its file. If the database cannot
confirm the outcome, the API returns `upload_status_unknown` and preserves the
file. Failed compensation returns `cleanup_failed`. Both require operator
reconciliation; deleting an uncertain file could destroy a committed upload.
Process termination between file promotion and commit can also leave an orphan.

There is no automatic retention timer or file deletion endpoint yet. Database
cascade deletion does not delete files. Operators must set a retention policy,
back up the database and storage together, and reconcile generated files against
`documents.storage_path` before deleting orphaned files. The coordinated reconciler below also includes
staging files left by interrupted writes. Do not log file contents or patient
filenames; this prototype should use synthetic documents.

## Container persistence verification

The full PostgreSQL/API/worker compose smoke in [deployment.md](deployment.md)
replaces the earlier isolated SQLite container fixture. It exercises actual HTTP
uploads, durable processing, review, restart, paired backup/restore and rollback.

## Crash and uncertain-commit reconciliation

Upload persistence and the reconciler now hold the same PostgreSQL transaction
advisory lock keyed by the canonical upload root. Reconciliation obtains a fresh
READ COMMITTED reference snapshot **after** acquiring that lock. An upload's
commit/rollback finishes before cleanup can inspect it, including when the client
lost the commit acknowledgement. All API containers must use the same canonical
UPLOAD_DIR path for this volume (compose uses `/data/uploads`).

```bash
uv run --locked python -m scripts.reconcile_uploads
uv run --locked python -m scripts.reconcile_uploads --apply
```

The default reports counts. `--apply` removes only unreferenced generated UUID
PDF/JPEG/PNG files and `.upload-` staging files, preserving committed documents,
unrecognized names, directories, and symlinks. Missing referenced files produce
an unsuccessful exit for operator investigation; metadata is retained. DB/storage
failure stops cleanup with a safe code. No deletion occurs before confirming DB
access and acquiring the lock. Re-run after crash or failed cleanup; persistent
filesystem permission/hardware failures require fixing storage first.

Container startup runs reconciliation as a controlled pre-API step, so recoverable
crash artifacts are cleared before the demo accepts uploads. This is eventual
reconciliation, not an atomic transaction across PostgreSQL and the filesystem.
No implementation can promise instantaneous cleanup while storage is unavailable.
PostgreSQL tests cover actual process-crash artifacts and overlapping upload commits.
