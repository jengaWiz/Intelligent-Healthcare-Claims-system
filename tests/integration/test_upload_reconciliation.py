import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from models import Document
from services.upload_reconciliation import reconcile, storage_lock
from tests.integration.test_jobs import jobs_db as _jobs_db

jobs_db = _jobs_db
pytestmark = pytest.mark.integration


def test_reconciliation_retains_committed_and_removes_crash_artifacts(jobs_db, tmp_path):
    factory, document = jobs_db
    doc = document()
    committed = tmp_path / f"{uuid4().hex}.pdf"
    committed.write_bytes(b"%PDF-accepted")
    with factory.begin() as db:
        db.get(Document, doc).storage_path = str(committed)
    crashed = tmp_path / f"{uuid4().hex}.pdf"
    code = "import os,sys;from pathlib import Path;Path(sys.argv[1]).write_bytes(b'%PDF-crash');os._exit(9)"
    assert subprocess.run([sys.executable, "-c", code, str(crashed)], timeout=5).returncode == 9
    stage = tmp_path / ".upload-abcdefgh"
    stage.write_bytes(b"unfinished")
    arbitrary = tmp_path / "operator-note.txt"
    arbitrary.write_text("retain")
    outside = tmp_path.parent / f"{uuid4().hex}.pdf"
    outside.write_bytes(b"retain")
    symlink = tmp_path / f"{uuid4().hex}.pdf"
    symlink.symlink_to(outside)
    try:
        with factory.begin() as db:
            counts = reconcile(db, tmp_path)
        assert counts == {"referenced": 1, "orphans": 2, "removed": 0, "ignored": 2, "missing": 0}
        assert crashed.exists() and stage.exists()
        with factory.begin() as db:
            applied = reconcile(db, tmp_path, apply=True)
        assert applied["removed"] == 2
        assert (
            committed.exists() and arbitrary.exists() and outside.exists() and symlink.is_symlink()
        )
        assert not crashed.exists() and not stage.exists()
        with factory.begin() as db:
            assert reconcile(db, tmp_path, apply=True)["removed"] == 0
    finally:
        outside.unlink()


def test_reconciliation_waits_for_upload_commit(jobs_db, tmp_path):
    factory, document = jobs_db
    doc = document()
    path = tmp_path / f"{uuid4().hex}.pdf"
    started = Event()

    def cleanup():
        started.set()
        with factory.begin() as db:
            return reconcile(db, tmp_path, apply=True)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory.begin() as uploading:
            storage_lock(uploading, tmp_path)
            path.write_bytes(b"%PDF-in-flight")
            uploading.get(Document, doc).storage_path = str(path)
            uploading.flush()
            pending = pool.submit(cleanup)
            assert started.wait(timeout=5)
            assert not pending.done()
        result = pending.result(timeout=5)
    assert result["removed"] == 0 and result["referenced"] == 1
    assert path.exists()


def test_reconciliation_marks_missing_files_without_deleting_rows(jobs_db, tmp_path):
    factory, document = jobs_db
    doc = document()
    with factory.begin() as db:
        db.get(Document, doc).storage_path = str(tmp_path / f"{uuid4().hex}.pdf")
    with factory.begin() as db:
        assert reconcile(db, tmp_path, apply=True)["missing"] == 1
        assert db.get(Document, doc) is not None
