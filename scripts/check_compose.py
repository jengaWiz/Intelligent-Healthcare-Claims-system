"""Verify full local containers, restart durability, paired restore, and image rollback."""

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

from scripts.backup_demo import backup, compose, restore_to_fresh_project


def main():
    root = Path(__file__).resolve().parents[1]
    credentials = dict(
        line.split("=", 1)
        for line in (root / ".env.docker").read_text().splitlines()
        if line and not line.startswith("#")
    )
    project = "claims-smoke-" + uuid4().hex[:8]
    restored = project + "-restore"
    origin = "http://127.0.0.1:18047"
    os.environ["DEMO_PORT"] = "18047"
    os.environ["PUBLIC_ORIGIN"] = origin
    command = compose(project)
    restore_command = compose(restored)
    headers = {"Authorization": "Bearer " + credentials["API_AUTH_TOKEN"]}
    started = time.monotonic()
    checks = []

    def request(path, method="GET", payload=None, body=None, content_type=None):
        data = json.dumps(payload).encode() if payload is not None else body
        selected = {**headers}
        if data is not None:
            selected["Content-Type"] = content_type or "application/json"
        req = urllib.request.Request(origin + path, data=data, headers=selected, method=method)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def poll(claim_id, state):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            data = request(f"/claims/{claim_id}/results")
            if data["claim"]["state"] == state:
                return data
            time.sleep(0.2)
        raise AssertionError("Synthetic processing did not reach expected state")

    def upload(scenario):
        claim = request("/claims", "POST", {"source_system": "compose-smoke"})
        boundary = uuid4().hex
        data = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{scenario}.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
            + (root / f"samples/{scenario}.pdf").read_bytes()
            + f"\r\n--{boundary}--\r\n".encode()
        )
        doc = request(
            f"/claims/{claim['claim_id']}/documents",
            "POST",
            body=data,
            content_type="multipart/form-data; boundary=" + boundary,
        )
        job = request(f"/documents/{doc['document_id']}/extract", "POST")
        return claim["claim_id"], doc["document_id"], job["job_id"]

    try:
        # Upgrade an existing M1 dataset, not just an empty current-schema DB.
        subprocess.run([*command, "up", "-d", "--wait", "db"], check=True)
        subprocess.run(
            [*command, "run", "--rm", "migrate", "alembic", "upgrade", "b61ceaf00211"], check=True
        )
        seeded = subprocess.run(
            [
                *command,
                "run",
                "--rm",
                "--no-deps",
                "api",
                "python",
                "-m",
                "scripts.seed_m1_upgrade",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        legacy = json.loads(seeded.stdout)["claim_id"]
        subprocess.run([*command, "up", "-d", "--wait", "--wait-timeout", "90"], check=True)
        assert request("/health/ready")["status"] == "ready"
        checks.append("controlled_migrations_and_readiness")
        old = request(f"/claims/{legacy}/results")
        assert old["claim"]["version"] == 3 and len(old["reviews"]) == 1
        assert old["risk"] is None and old["current"]["data"]["billing"]["total_amount"] == "42.50"
        checks.append("m1_existing_results_migrate_without_risk_backfill")
        valid, valid_doc, _ = upload("valid")
        complete = poll(valid, "READY")
        assert complete["current"]["data"]["billing"]["total_amount"] == "42.50"
        checks.append("successful_fixture_extraction")
        assert complete["risk"]["level"] == "LOW"
        acknowledgment = request(
            f"/claims/{valid}/risk/acknowledgments",
            "POST",
            {
                "expected_version": complete["claim"]["version"],
                "assessment_id": complete["risk"]["assessment_id"],
                "reason": "Synthetic container risk investigation",
            },
        )
        review, _, _ = upload("review")
        pending = poll(review, "REVIEW_REQUIRED")
        assert pending["risk"]["level"] == "INSUFFICIENT_DATA"
        corrected = request(
            f"/claims/{review}/reviews",
            "POST",
            {
                "expected_version": pending["claim"]["version"],
                "decision": "correct",
                "reason": "Synthetic compose verification",
                "corrections": {
                    "patient_name": "Synthetic Example",
                    "patient_dob": "1980-01-01",
                    "provider_name": "Synthetic Clinic",
                    "service_date": "2026-10-01",
                    "total_amount": "48.75",
                },
            },
        )
        assert corrected["claim"]["state"] == "READY" and len(corrected["reviews"]) == 1
        assert corrected["risk"]["level"] == "LOW"
        checks.append("missing_amount_low_confidence_correction_audit")
        failed, failed_doc, previous_job = upload("failure")
        assert poll(failed, "FAILED")["job"]["error"]["code"] == "invalid_provider_response"
        retry = request(f"/documents/{failed_doc}/extract", "POST")
        assert retry["job_id"] != previous_job
        poll(failed, "FAILED")
        checks.append("safe_failure_fresh_retry")
        subprocess.run([*command, "stop", "worker"], check=True)
        queued, _, _ = upload("valid")
        subprocess.run([*command, "restart", "api"], check=True)
        for _ in range(100):
            try:
                assert request(f"/claims/{queued}/results")["job"]["state"] == "QUEUED"
                break
            except (OSError, AssertionError):
                time.sleep(0.2)
        else:
            raise AssertionError("API restart did not preserve queued job")
        subprocess.run([*command, "start", "worker"], check=True)
        queued_result = poll(queued, "READY")
        assert queued_result["risk"]["level"] == "HIGH"
        assert "possible_duplicate_document" in {
            item["code"] for item in queued_result["risk"]["signals"]
        }
        checks.append("api_worker_restart_queue_durability")
        assert request(f"/claims/{valid}/results")["risk_acknowledgment"] == acknowledgment
        assert request(f"/claims/{valid}/results")["risk"] == complete["risk"]
        checks.append("risk_history_acknowledgment_survive_restart")
        medium, _, _ = upload("medium")
        assert poll(medium, "READY")["risk"]["level"] == "MEDIUM"
        high, _, _ = upload("high")
        assert poll(high, "REVIEW_REQUIRED")["risk"]["level"] == "HIGH"
        checks.append("risk_levels_and_scoped_exact_duplicate_signal")
        # All seven files, including the legacy fixture, must survive intact.
        verify = "from sqlalchemy import create_engine,select;from sqlalchemy.orm import Session;from config.settings import Settings;from models import Document,RiskAssessment,RiskAcknowledgment;from pathlib import Path;from hashlib import sha256;s=Settings();db=Session(create_engine(s.require_database_url()));docs=db.scalars(select(Document)).all();assert len(docs)==7;assert all(sha256(Path(d.storage_path).read_bytes()).hexdigest()==d.sha256 for d in docs);assert len(db.scalars(select(RiskAssessment)).all())==6;assert len(db.scalars(select(RiskAcknowledgment)).all())==1"
        subprocess.run([*command, "exec", "-T", "api", "python", "-c", verify], check=True)
        with tempfile.TemporaryDirectory(prefix="claims-backup-") as directory:
            target = Path(directory) / "paired"
            backup(project, target)
            assert json.loads((target / "manifest.json").read_text())["schema"] == "968da3f6918e"
            # Keep source volumes untouched; stop its network services to free the port.
            subprocess.run([*command, "stop", "api", "worker"], check=True)
            restore_to_fresh_project(restored, target)
            assert request(f"/claims/{valid}/results")["current"] == complete["current"]
            assert len(request(f"/claims/{review}/reviews")) == 1
            assert request(f"/claims/{valid}/results")["risk"] == complete["risk"]
            assert request(f"/claims/{valid}/results")["risk_acknowledgment"] == acknowledgment
            assert request(f"/claims/{legacy}/results")["risk"] is None
            subprocess.run(
                [*restore_command, "exec", "-T", "api", "python", "-c", verify], check=True
            )
            checks.append("paired_database_upload_restore_preserves_audit")
            checks.append("paired_restore_preserves_risk_history_ack_and_legacy_data")
        # Rehearse choosing the retained immutable image ID instead of a mutable tag.
        image = subprocess.run(
            [*restore_command, "images", "-q", "api"], capture_output=True, text=True, check=True
        ).stdout.strip()
        os.environ["CLAIMS_IMAGE"] = image
        subprocess.run(
            [
                *restore_command,
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "90",
                "api",
                "worker",
            ],
            check=True,
        )
        assert request(f"/claims/{valid}/results")["claim"]["state"] == "READY"
        checks.append("retained_image_redeploy_rollback_rehearsal")
        report = {
            "synthetic_only": True,
            "live_provider_calls": 0,
            "checks": checks,
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
        report_path = root / "docs/verification/compose.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
        return 0
    finally:
        # Delete only these randomly named disposable smoke projects/volumes.
        os.environ.pop("CLAIMS_IMAGE", None)
        for cleanup in (command, restore_command):
            subprocess.run([*cleanup, "down", "--volumes", "--remove-orphans"], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
