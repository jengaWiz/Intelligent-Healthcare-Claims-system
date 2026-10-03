"""Upgrade a populated isolated M1 database and refuse unsafe fixture seeding."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from config.settings import Settings
from models import Claim, Document, RiskAssessment
from scripts.seed_m1_upgrade import seed
from services.review_service import result_projection
from services.upload_reconciliation import MANAGED

pytestmark = pytest.mark.integration


def test_populated_m1_upgrade_preserves_evidence_without_risk_backfill(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    admin = create_engine(url, isolation_level="AUTOCOMMIT", hide_parameters=True)
    name = "claims_risk_upgrade_" + uuid4().hex
    target = admin.url.set(database=name).render_as_string(hide_password=False)
    with admin.connect() as connection:
        connection.execute(text(f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8'"))
    try:
        env = {**os.environ, "DATABASE_URL": target}
        root = Path(__file__).resolve().parents[2]
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "b61ceaf00211"],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
        settings = Settings(
            _env_file=None, database_url=target, synthetic_mode=True, upload_dir=tmp_path
        )
        legacy = seed(settings)
        assert len(list(tmp_path.glob("*.pdf"))) == 1
        assert MANAGED.fullmatch(next(tmp_path.glob("*.pdf")).name)
        assert next(tmp_path.glob("*.pdf")).stat().st_mode & 0o777 == 0o600
        with pytest.raises(ValueError, match="empty M1 test database"):
            seed(settings)
        assert len(list(tmp_path.glob("*.pdf"))) == 1
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
        engine = create_engine(target, hide_parameters=True)
        try:
            with Session(engine) as db:
                db.info["actor_id"] = "api"
                result = result_projection(db, UUID(legacy["claim_id"]))
                assert result["claim"].version == 3 and result["claim"].state == "READY"
                assert result["current"]["data"]["billing"]["total_amount"] == "42.50"
                assert len(result["reviews"]) == 1 and result["risk"] is None
                assert db.scalar(select(func.count()).select_from(RiskAssessment)) == 0
                assert db.scalar(select(func.count()).select_from(Claim)) == 1
                document = db.scalar(select(Document))
                from hashlib import sha256

                assert (
                    sha256(Path(document.storage_path).read_bytes()).hexdigest() == document.sha256
                )
            with pytest.raises(ValueError, match="empty M1 test database"):
                seed(settings)
        finally:
            engine.dispose()
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
