"""Atomic, private uploads with generated names in a configured durable directory."""

import os
import tempfile
import uuid
from pathlib import Path

EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


class StorageError(Exception):
    pass


def delete_file(storage_path: str, upload_dir: Path) -> None:
    root = upload_dir.resolve()
    path = Path(storage_path)
    if path.resolve().parent != root:
        raise StorageError("Storage path is outside the upload directory")
    path.unlink(missing_ok=True)


def save_file(file_bytes: bytes, mime_type: str, upload_dir: Path) -> str:
    root = upload_dir.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / f"{uuid.uuid4().hex}{EXTENSIONS[mime_type]}"
    temporary = None
    promoted = False
    try:
        descriptor, name = tempfile.mkstemp(prefix=".upload-", dir=root)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(file_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        promoted = True
        # Persist the directory entry as well as the file before DB commit.
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return str(destination)
    except OSError as exc:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if promoted:
                destination.unlink(missing_ok=True)
        except OSError as cleanup:
            raise StorageError("Upload storage cleanup failed") from cleanup
        raise StorageError("Upload storage failed") from exc
