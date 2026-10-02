import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool

from api.documents import read_file
from api.main import create_app
from config.settings import Settings
from models import Claim, Document

pytestmark = pytest.mark.integration


def test_concurrent_uploads_and_restart_persistence(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated migrated database")
    engine = create_engine(url)
    factory = sessionmaker(bind=engine)
    settings = Settings(
        _env_file=None, api_auth_token="synthetic-upload-token", upload_dir=tmp_path / "uploads"
    )
    app = create_app(settings, session_factory=factory)
    headers = {"Authorization": "Bearer synthetic-upload-token"}
    claim_id = None
    content = b"%PDF-1.7 synthetic upload fixture"
    try:
        with TestClient(app) as client:
            created = client.post("/claims", json={}, headers=headers)
            assert created.status_code == 201
            claim_id = UUID(created.json()["claim_id"])
        barrier = Barrier(2)

        async def synchronized_read(file, limit):
            result = await read_file(file, limit)
            await run_in_threadpool(barrier.wait, 10)
            return result

        def upload():
            with TestClient(app) as client:
                return client.post(
                    f"/claims/{claim_id}/documents",
                    headers=headers,
                    files={"file": ("synthetic.pdf", content, "application/pdf")},
                )

        with patch("api.documents.read_file", side_effect=synchronized_read):
            with ThreadPoolExecutor(max_workers=2) as workers:
                responses = list(workers.map(lambda _: upload(), range(2)))
        assert sorted(response.status_code for response in responses) == [201, 409]
        successful = next(response for response in responses if response.status_code == 201)
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count()).select_from(Document).where(Document.claim_id == claim_id)
                )
                == 1
            )
            doc = db.get(Document, UUID(successful.json()["document_id"]))
            path = Path(doc.storage_path)
            assert path.read_bytes() == content
        with TestClient(create_app(settings, session_factory=factory)) as restarted:
            assert (
                restarted.get(successful.headers["location"], headers=headers).json()
                == successful.json()
            )
            assert path.read_bytes() == content
        assert len(list(settings.upload_dir.iterdir())) == 1
    finally:
        if claim_id is not None:
            with engine.begin() as connection:
                connection.execute(delete(Claim).where(Claim.claim_id == claim_id))
        engine.dispose()
