"""Synthetic API smoke: create in one container, verify from a fresh container.

Use only a disposable directory. SQLite supplies the smoke database; the separate
PostgreSQL integration suite verifies concurrent transaction behavior.
"""

import argparse
import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import create_app
from config.settings import Settings
from models import Claim, Document


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["create", "verify"])
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{args.data_dir / 'smoke.db'}", connect_args={"check_same_thread": False}
    )
    if args.mode == "create":
        Claim.__table__.create(engine, checkfirst=True)
        Document.__table__.create(engine, checkfirst=True)
    factory = sessionmaker(bind=engine)
    token = "synthetic-container-smoke-token"
    settings = Settings(_env_file=None, api_auth_token=token, upload_dir=args.data_dir / "uploads")
    headers = {"Authorization": f"Bearer {token}"}
    sample = b"%PDF-1.7 synthetic container persistence fixture"
    try:
        with TestClient(create_app(settings, session_factory=factory)) as client:
            if args.mode == "create":
                response = client.post("/claims", json={}, headers=headers)
                assert response.status_code == 201, response.text
                claim_id = response.json()["claim_id"]
                uploaded = client.post(
                    f"/claims/{claim_id}/documents",
                    headers=headers,
                    files={"file": ("synthetic.pdf", sample, "application/pdf")},
                )
                assert uploaded.status_code == 201, uploaded.text
                (args.data_dir / "expected.json").write_text(json.dumps(uploaded.json()))
            else:
                expected = json.loads((args.data_dir / "expected.json").read_text())
                response = client.get(f"/documents/{expected['document_id']}", headers=headers)
                assert response.status_code == 200 and response.json() == expected
                with factory() as db:
                    path = Path(db.get(Document, UUID(expected["document_id"])).storage_path)
                    assert path.read_bytes() == sample
                assert len(list(settings.upload_dir.iterdir())) == 1
        print(f"Upload container smoke {args.mode}: passed")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
