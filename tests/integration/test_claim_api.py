import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.main import create_app
from config.settings import Settings
from models import Claim

pytestmark = pytest.mark.integration


def test_claim_api_commits_and_retrieves_in_postgresql():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated migrated database")
    engine = create_engine(url)
    with engine.connect() as connection:
        outer = connection.begin()
        factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
        token = "synthetic-api-token"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with TestClient(
                create_app(Settings(_env_file=None, api_auth_token=token), session_factory=factory)
            ) as client:
                created = client.post(
                    "/claims", json={"source_system": "synthetic-api"}, headers=headers
                )
                assert created.status_code == 201
                claim_id = UUID(created.json()["claim_id"])
                fetched = client.get(f"/claims/{claim_id}", headers=headers)
                assert fetched.status_code == 200 and fetched.json() == created.json()
                assert client.get(f"/claims/{uuid4()}", headers=headers).status_code == 404
                assert client.get("/claims/invalid", headers=headers).status_code == 422
                assert client.get("/health/ready", headers=headers).status_code == 200
                with factory() as db:
                    assert db.get(Claim, claim_id).source_system == "synthetic-api"
        finally:
            outer.rollback()
    engine.dispose()
