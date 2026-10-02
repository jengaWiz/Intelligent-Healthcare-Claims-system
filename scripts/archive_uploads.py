"""Binary upload archive helper; restore permits only generated regular files."""

import argparse
import os
import sys
import tarfile
from pathlib import Path

from services.upload_reconciliation import MANAGED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    args = parser.parse_args()
    root = Path(os.environ["UPLOAD_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.operation == "backup":
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            for path in sorted(root.iterdir()):
                if MANAGED.fullmatch(path.name) and path.is_file() and not path.is_symlink():
                    archive.add(path, arcname=path.name, recursive=False)
    else:
        with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
            for member in archive:
                if (
                    not member.isfile()
                    or not MANAGED.fullmatch(member.name)
                    or member.size > 100 * 1024 * 1024
                ):
                    raise ValueError("Archive contains an unsupported member")
                # Never overwrite live uploads. Restore only to a fresh volume.
                with (root / member.name).open("xb") as target:
                    os.chmod(root / member.name, 0o600)
                    source = archive.extractfile(member)
                    while chunk := source.read(65536):
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())


if __name__ == "__main__":
    main()
