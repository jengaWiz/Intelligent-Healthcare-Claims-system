"""Create paired private database/uploads backups with API and worker quiesced."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def compose(project):
    return ["docker", "compose", "--env-file", ".env.docker", "-p", project]


def backup(project, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    command = compose(project)
    # All writes must stop so the database and volume share a consistent point.
    subprocess.run([*command, "stop", "api", "worker"], check=True)
    try:
        with (directory / "database.dump").open("xb") as stream:
            os.chmod(directory / "database.dump", 0o600)
            subprocess.run(
                [*command, "exec", "-T", "db", "pg_dump", "-U", "claims", "-d", "claims", "-Fc"],
                stdout=stream,
                check=True,
            )
        with (directory / "uploads.tar").open("xb") as stream:
            os.chmod(directory / "uploads.tar", 0o600)
            subprocess.run(
                [
                    *command,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "api",
                    "python",
                    "-m",
                    "scripts.archive_uploads",
                    "backup",
                ],
                stdout=stream,
                check=True,
            )
        files = {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in ("database.dump", "uploads.tar")
        }
        metadata = {
            "created_at": datetime.now(UTC).isoformat(),
            "project": project,
            "sha256": files,
            "schema": "b61ceaf00211",
        }
        (directory / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
        os.chmod(directory / "manifest.json", 0o600)
    finally:
        subprocess.run([*command, "start", "api", "worker"], check=True)


def restore_to_fresh_project(project, directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    for name in ("database.dump", "uploads.tar"):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest["sha256"][name]:
            raise ValueError("Backup checksum mismatch")
    command = compose(project)
    # Caller must choose a NEW project, with no running API/worker or uploads.
    status = subprocess.run(
        [*command, "ps", "-q", "--all"], capture_output=True, text=True, check=True
    )
    if status.stdout.strip():
        raise ValueError("Restore requires a fresh compose project")
    subprocess.run([*command, "up", "-d", "--wait", "db"], check=True)
    with (directory / "database.dump").open("rb") as stream:
        subprocess.run(
            [
                *command,
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                "claims",
                "-d",
                "claims",
                "--no-owner",
                "--exit-on-error",
            ],
            stdin=stream,
            check=True,
        )
    with (directory / "uploads.tar").open("rb") as stream:
        subprocess.run(
            [
                *command,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "api",
                "python",
                "-m",
                "scripts.archive_uploads",
                "restore",
            ],
            stdin=stream,
            check=True,
        )
    subprocess.run([*command, "up", "-d", "--wait", "--wait-timeout", "90"], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--project", default="claims-demo")
    args = parser.parse_args()
    if args.operation == "backup":
        backup(args.project, args.directory)
    else:
        if args.project == "claims-demo":
            parser.error("Restore requires --project with a NEW project name")
        restore_to_fresh_project(args.project, args.directory)
    print("Paired backup operation completed")


if __name__ == "__main__":
    main()
