"""Archive restore cannot traverse, follow links, or replace accepted files."""

import io
import os
import subprocess
import sys
import tarfile
from uuid import uuid4

import pytest


def archive(member, data=b"synthetic"):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as output:
        if member.isfile():
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
        else:
            output.addfile(member)
    return stream.getvalue()


def restore(data, root):
    return subprocess.run(
        [sys.executable, "-m", "scripts.archive_uploads", "restore"],
        env={**os.environ, "UPLOAD_DIR": str(root)},
        input=data,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("name", ["../escape.pdf", "/tmp/escape.pdf", "operator-note.txt"])
def test_restore_rejects_unmanaged_and_traversal_names(tmp_path, name):
    assert restore(archive(tarfile.TarInfo(name)), tmp_path).returncode != 0
    assert not list(tmp_path.iterdir())


def test_restore_rejects_symlinks_and_existing_destinations(tmp_path):
    name = uuid4().hex + ".pdf"
    link = tarfile.TarInfo(name)
    link.type = tarfile.SYMTYPE
    link.linkname = "../escape"
    assert restore(archive(link), tmp_path).returncode != 0
    valid = archive(tarfile.TarInfo(name))
    assert restore(valid, tmp_path).returncode == 0
    assert (tmp_path / name).read_bytes() == b"synthetic"
    assert restore(valid, tmp_path).returncode != 0
    assert (tmp_path / name).read_bytes() == b"synthetic"
