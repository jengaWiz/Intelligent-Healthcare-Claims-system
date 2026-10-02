"""Reconcile only generated upload files under the same DB lock as upload commits."""

import re
import stat
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select, text

from models import Document

MANAGED = re.compile(r"(?:[0-9a-f]{32}\.(?:pdf|jpg|png)|\.upload-[A-Za-z0-9_-]{8})\Z")


def storage_lock(db, upload_dir):
    # Tests may use SQLite; deployed/API integration always uses PostgreSQL.
    if db.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(
            sha256(str(upload_dir.resolve()).encode()).digest()[:8], "big", signed=True
        )
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def reconcile(db, upload_dir, *, apply=False):
    if not db.in_transaction():
        raise ValueError("Reconciliation requires an explicit transaction")
    root = upload_dir.resolve()
    storage_lock(db, root)
    # A failed/uncertain commit has finished before this lock is granted. Use a
    # fresh READ COMMITTED snapshot after acquiring it, never before.
    referenced = {Path(path).absolute() for path in db.scalars(select(Document.storage_path))}
    counts = {"referenced": 0, "orphans": 0, "removed": 0, "ignored": 0, "missing": 0}
    for path in referenced:
        if path.parent == root and not path.is_file():
            counts["missing"] += 1
    if not root.exists():
        return counts
    for path in root.iterdir():
        if not MANAGED.fullmatch(path.name) or not stat.S_ISREG(path.lstat().st_mode):
            counts["ignored"] += 1
        elif path in referenced:
            counts["referenced"] += 1
        else:
            counts["orphans"] += 1
            if apply:
                path.unlink(missing_ok=True)
                counts["removed"] += 1
    return counts
