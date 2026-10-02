"""Real session revocation and ownership across every HTTP record boundary."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.main import create_app
from config.settings import Settings
from models import BrowserSession, Claim
from tests.integration.test_jobs import jobs_db as _jobs_db

jobs_db = _jobs_db
pytestmark = pytest.mark.integration
ORIGIN = "http://127.0.0.1:8000"


def test_sessions_csrf_ownership_and_revocation(jobs_db, tmp_path):
    factory, _ = jobs_db
    settings = Settings(
        _env_file=None,
        api_auth_token="operator-token",
        demo_password="synthetic-password",
        session_secure=False,
        upload_dir=tmp_path,
    )
    app = create_app(settings, session_factory=factory)
    owners = []
    with TestClient(app) as first, TestClient(app) as second:
        assert first.post("/auth/login", json={"password": "synthetic-password"}).status_code == 403
        assert (
            first.post(
                "/auth/login", headers={"Origin": ORIGIN}, json={"password": "wrong"}
            ).status_code
            == 401
        )
        login = first.post(
            "/auth/login", headers={"Origin": ORIGIN}, json={"password": "synthetic-password"}
        )
        assert login.status_code == 200, login.text
        assert (
            "HttpOnly" in login.headers["set-cookie"]
            and "SameSite=strict" in login.headers["set-cookie"]
        )
        headers = {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]}
        owners.append(first.get("/auth/session").json()["actor_id"])
        assert first.post("/claims", json={}).status_code == 403
        assert (
            first.post(
                "/claims", headers={**headers, "Origin": "https://attacker.example"}, json={}
            ).status_code
            == 403
        )
        created = first.post("/claims", headers=headers, json={})
        claim_id = created.json()["claim_id"]
        upload = first.post(
            f"/claims/{claim_id}/documents",
            headers=headers,
            files={"file": ("synthetic.pdf", b"%PDF-synthetic", "application/pdf")},
        )
        doc_id = upload.json()["document_id"]
        job = first.post(f"/documents/{doc_id}/extract", headers=headers).json()["job_id"]
        second.post(
            "/auth/login", headers={"Origin": ORIGIN}, json={"password": "synthetic-password"}
        )
        owners.append(second.get("/auth/session").json()["actor_id"])
        csrf2 = second.get("/auth/session").json()["csrf_token"]
        for path in (
            f"/claims/{claim_id}",
            f"/claims/{claim_id}/results",
            f"/claims/{claim_id}/reviews",
            f"/documents/{doc_id}",
            f"/jobs/{job}",
        ):
            assert second.get(path).status_code == 404, path
            assert first.get(path).status_code == 200, path
            assert (
                first.get(path, headers={"Authorization": "Bearer operator-token"}).status_code
                == 404
            )
        assert (
            second.post(
                f"/documents/{doc_id}/extract", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf2}
            ).status_code
            == 404
        )
        assert second.get("/reviews").json() == []
        cookie = first.cookies.get("claims_session")
        assert first.post("/auth/logout", headers=headers).status_code == 200
        assert first.get(f"/claims/{claim_id}").status_code == 401
        first.cookies.set("claims_session", cookie)
        assert first.get(f"/claims/{claim_id}").status_code == 401
    with factory.begin() as db:
        db.execute(delete(Claim).where(Claim.owner_id.in_(owners)))
        db.execute(delete(BrowserSession).where(BrowserSession.actor_id.in_(owners)))


def test_login_rate_and_request_limit(jobs_db):
    factory, _ = jobs_db
    app = create_app(
        Settings(_env_file=None, demo_password="synthetic", session_secure=False),
        session_factory=factory,
    )
    with TestClient(app) as client:
        for _ in range(10):
            assert (
                client.post(
                    "/auth/login", headers={"Origin": ORIGIN}, json={"password": "wrong"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/auth/login", headers={"Origin": ORIGIN}, json={"password": "wrong"}
            ).status_code
            == 429
        )
        assert (
            client.post(
                "/auth/login", content=b"x" * 65537, headers={"content-type": "application/json"}
            ).status_code
            == 413
        )


def test_expired_session_and_safe_request_logs(jobs_db, caplog):
    from datetime import UTC, datetime, timedelta
    from hashlib import sha256

    factory, _ = jobs_db
    settings = Settings(
        _env_file=None,
        demo_password="synthetic-secret",
        session_secure=False,
        allowed_origins=[ORIGIN],
    )
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as client:
        with caplog.at_level("INFO", logger="claims.http"):
            login = client.post(
                "/auth/login", headers={"Origin": ORIGIN}, json={"password": "synthetic-secret"}
            )
            cookie = client.cookies.get("claims_session")
            assert login.status_code == 200
            assert client.get("/auth/session").status_code == 200
        assert "synthetic-secret" not in caplog.text and cookie not in caplog.text
        assert "request_id=" in caplog.text and "route=/auth/login" in caplog.text
        allowed = client.options(
            "/claims",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert allowed.headers["access-control-allow-origin"] == ORIGIN
        denied = client.options(
            "/claims",
            headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "POST"},
        )
        assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
        with factory.begin() as db:
            session = db.get(BrowserSession, sha256(cookie.encode()).hexdigest())
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert client.get("/auth/session").status_code == 401
        with factory.begin() as db:
            db.execute(
                delete(BrowserSession).where(
                    BrowserSession.token_hash == sha256(cookie.encode()).hexdigest()
                )
            )


@pytest.mark.parametrize("timezone", ["Etc/GMT-14", "Etc/GMT+12"])
def test_session_expiry_uses_the_instant_not_database_timezone(jobs_db, timezone):
    import os
    from datetime import UTC, datetime, timedelta
    from hashlib import sha256

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(
        os.environ["TEST_DATABASE_URL"],
        hide_parameters=True,
        connect_args={"options": "-c TimeZone=" + timezone},
    )
    factory = sessionmaker(bind=engine)
    app = create_app(
        Settings(
            _env_file=None,
            demo_password="synthetic-timezone",
            session_secure=False,
            session_seconds=60,
        ),
        session_factory=factory,
    )
    digest = None
    try:
        with TestClient(app) as client:
            assert (
                client.post(
                    "/auth/login",
                    headers={"Origin": ORIGIN},
                    json={"password": "synthetic-timezone"},
                ).status_code
                == 200
            )
            digest = sha256(client.cookies.get("claims_session").encode()).hexdigest()
            assert client.get("/auth/session").status_code == 200
            with factory.begin() as db:
                db.get(BrowserSession, digest).expires_at = datetime.now(UTC) - timedelta(seconds=1)
            assert client.get("/auth/session").status_code == 401
    finally:
        if digest:
            with factory.begin() as db:
                db.execute(delete(BrowserSession).where(BrowserSession.token_hash == digest))
        engine.dispose()
