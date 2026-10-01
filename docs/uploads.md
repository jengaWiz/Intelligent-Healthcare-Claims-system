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
`documents.storage_path` before deleting orphaned files. Stop uploads/workers
while reconciling; include staging files left by interrupted writes. Do not log
file contents or patient filenames. Automated lifecycle handling remains future
work; this prototype should use synthetic documents.

## Container recreation smoke check

The following isolated fixture exercises actual API handlers without providers.
It stores synthetic SQLite metadata and uploads in the same mounted directory;
production uses PostgreSQL separately. It verifies persistence, not production
packaging or a deployed HTTP server.

```bash
docker build -f tests/containers/uploads.Dockerfile -t claims-upload-smoke:m1 .
mkdir -p /tmp/claims-upload-smoke
# Use a fresh dedicated directory for each run.
docker run --rm --mount type=bind,source=/tmp/claims-upload-smoke,target=/data \
  claims-upload-smoke:m1 /app/.venv/bin/python /app/smoke.py create --data-dir /data
docker run --rm --mount type=bind,source=/tmp/claims-upload-smoke,target=/data \
  claims-upload-smoke:m1 /app/.venv/bin/python /app/smoke.py verify --data-dir /data
```

Each command creates and removes a separate container. The second must retrieve
the original document metadata and verify the stored bytes. PostgreSQL integration
tests additionally exercise concurrent uploads and persistence across app instances.
