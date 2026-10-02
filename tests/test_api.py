from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import create_app
from config.settings import Settings
from models import Claim

TOKEN = "synthetic-api-test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Claim.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    app = create_app(Settings(_env_file=None, api_auth_token=TOKEN), session_factory=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, factory
    engine.dispose()


def test_create_and_retrieve_claim_project_only_public_fields(api):
    client, factory = api
    created = client.post("/claims", headers=HEADERS, json={"source_system": "  synthetic-demo  "})
    assert created.status_code == 201
    claim = created.json()
    assert UUID(claim["claim_id"])
    assert created.headers["location"] == f"/claims/{claim['claim_id']}"
    assert set(claim) == {
        "claim_id",
        "state",
        "version",
        "source_system",
        "created_at",
        "updated_at",
    }
    assert claim["state"] == "RECEIVED" and claim["version"] == 1
    assert claim["source_system"] == "synthetic-demo"
    assert claim["created_at"].endswith("Z")
    # GET uses a separate session; the POST must commit before returning success.
    fetched = client.get(created.headers["location"], headers=HEADERS)
    assert fetched.status_code == 200 and fetched.json() == claim
    with factory() as db:
        assert db.get(Claim, UUID(claim["claim_id"])) is not None


@pytest.mark.parametrize(
    "body",
    [
        {"source_system": ""},
        {"source_system": "x" * 101},
        {"source_system": 123},
        {"storage_path": "/private/secret"},
    ],
)
def test_request_validation_is_safe(api, body):
    client, _ = api
    response = client.post("/claims", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id"}
    assert "/private/secret" not in response.text


def test_invalid_and_missing_ids(api):
    client, _ = api
    assert client.get("/claims/not-a-uuid", headers=HEADERS).status_code == 422
    missing = client.get(f"/claims/{uuid4()}", headers=HEADERS)
    assert missing.status_code == 404 and missing.json()["code"] == "claim_not_found"


def test_authentication_precedes_database_access():
    def no_database():
        raise AssertionError("Unauthorized request touched database")

    app = create_app(Settings(_env_file=None, api_auth_token=TOKEN), session_factory=no_database)
    with TestClient(app, raise_server_exceptions=False) as client:
        for headers in ({}, {"Authorization": "Bearer incorrect"}, {"Authorization": "Basic nope"}):
            response = client.post("/claims", json={}, headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.post("/claims", json={}).status_code == 503
        assert client.get("/health/live").json() == {"status": "ok"}


def test_liveness_independent_readiness_safe_and_bounded():
    with TestClient(create_app(Settings(_env_file=None, api_auth_token=TOKEN))) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready", headers=HEADERS)
        assert response.status_code == 503 and response.json()["code"] == "not_ready"
        assert "DATABASE_URL" not in response.text
    settings = Settings(
        _env_file=None,
        api_auth_token=TOKEN,
        database_url="postgresql+psycopg://synthetic:secret@host/test",
        database_timeout_seconds=2,
    )
    with patch(
        "api.main.create_engine", side_effect=RuntimeError("private provider error")
    ) as factory:
        with TestClient(create_app(settings)) as client:
            response = client.get("/health/ready", headers=HEADERS)
        assert response.status_code == 503 and "private" not in response.text
        kwargs = factory.call_args.kwargs
        assert kwargs["connect_args"]["connect_timeout"] == 2
        assert kwargs["connect_args"]["options"] == "-c statement_timeout=2000"
        assert kwargs["pool_timeout"] == 2


def test_internal_failure_rolls_back_and_redacts(api):
    client, factory = api
    from services.claim_service import create_claim

    def fail_after_insert(db, source):
        create_claim(db, source)
        raise RuntimeError("private secret and filesystem path")

    with patch("api.claims.create_claim", side_effect=fail_after_insert):
        response = client.post("/claims", headers=HEADERS, json={})
    assert response.status_code == 500
    assert "private" not in response.text
    assert UUID(response.json()["request_id"])
    assert response.headers["x-request-id"] == response.json()["request_id"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Claim)) == 0


def test_readiness_and_job_routes_require_auth(api):
    client, _ = api
    assert client.get("/health/ready", headers=HEADERS).json() == {"status": "ready"}
    assert client.post(f"/documents/{uuid4()}/extract").status_code == 401
    assert client.get(f"/jobs/{uuid4()}").status_code == 401


def test_openapi_documents_contract(api):
    client, _ = api
    schema = client.get("/openapi.json").json()
    assert "/claims" in schema["paths"] and "/health/ready" in schema["paths"]
    response_schema = schema["paths"]["/claims"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"].endswith("/ClaimResponse")
    assert schema["paths"]["/claims"]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/claims"]["post"]["responses"]["422"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("/ErrorResponse")


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", f"/claims/{uuid4()}", None),
        ("POST", "/claims", {}),
        ("GET", "/health/ready", None),
    ],
)
def test_database_outage_returns_safe_503(method, path, body):
    from sqlalchemy.exc import OperationalError

    def unavailable():
        raise OperationalError("SELECT 1", {}, RuntimeError("password=synthetic-secret"))

    app = create_app(Settings(_env_file=None, api_auth_token=TOKEN), session_factory=unavailable)
    with TestClient(app) as client:
        response = client.request(method, path, headers=HEADERS, json=body)
        assert response.status_code == 503
        assert "synthetic-secret" not in response.text
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert client.get("/health/live").status_code == 200
