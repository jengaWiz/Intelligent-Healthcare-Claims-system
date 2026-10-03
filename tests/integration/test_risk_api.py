"""Public risk APIs enforce ownership, versions, bounds and independent review."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.main import create_app
from config.settings import Settings
from models import BrowserSession, Claim, Document
from tests.integration.test_jobs import jobs_db as _jobs_db
from tests.integration.test_reviews import completed

jobs_db = _jobs_db
pytestmark = pytest.mark.integration
HEADERS = {"Authorization": "Bearer risk-operator-test"}
ORIGIN = "http://127.0.0.1:8000"


def application(factory):
    return create_app(
        Settings(
            _env_file=None,
            api_auth_token="risk-operator-test",
            demo_password="risk-browser-test",
            session_secure=False,
        ),
        session_factory=factory,
    )


def test_results_history_refresh_and_acknowledgment(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)
    with TestClient(application(factory)) as client:
        path = f"/claims/{claim_id}"
        result = client.get(path + "/results", headers=HEADERS).json()
        assessment = result["risk"]
        assert result["risk_acknowledgment"] is None
        assert "input_fingerprint" not in assessment and "context_fingerprint" not in assessment
        history = client.get(path + "/risk", headers=HEADERS).json()
        assert history["items"][0] == assessment and history["limit"] == 20
        for params in ({"limit": 101}, {"offset": -1}):
            assert client.get(path + "/risk", headers=HEADERS, params=params).status_code == 422
        assert (
            client.post(
                path + "/risk/refresh", headers=HEADERS, json={"expected_version": version}
            ).json()
            == assessment
        )
        assert (
            client.post(
                path + "/risk/refresh", headers=HEADERS, json={"expected_version": version - 1}
            ).json()["code"]
            == "stale_risk"
        )
        payload = {
            "expected_version": version,
            "assessment_id": assessment["assessment_id"],
            "reason": "Investigated synthetic evidence",
        }
        ack = client.post(path + "/risk/acknowledgments", headers=HEADERS, json=payload)
        assert ack.status_code == 200 and ack.json()["actor_id"] == "api"
        assert (
            client.post(path + "/risk/acknowledgments", headers=HEADERS, json=payload).json()
            == ack.json()
        )
        assert (
            client.get(path + "/results", headers=HEADERS).json()["claim"]["state"]
            == "REVIEW_REQUIRED"
        )
        for extra in ({"level": "LOW"}, {"actor_id": "stranger"}, {"policy_version": "other"}):
            assert (
                client.post(
                    path + "/risk/acknowledgments", headers=HEADERS, json={**payload, **extra}
                ).status_code
                == 422
            )
        assert (
            client.post(
                path + "/risk/acknowledgments",
                headers=HEADERS,
                json={**payload, "reason": "Changed"},
            ).json()["code"]
            == "risk_already_acknowledged"
        )
        correction = {
            "expected_version": version,
            "decision": "correct",
            "reason": "Checked source",
            "corrections": {
                "patient_name": "Synthetic",
                "provider_name": "Clinic",
                "service_date": "2026-10-01",
                "total_amount": "100001",
            },
        }
        updated = client.post(path + "/reviews", headers=HEADERS, json=correction).json()
        assert updated["claim"]["state"] == "READY" and updated["risk"]["level"] == "HIGH"
        assert updated["risk_acknowledgment"] is None
        assert (
            client.post(
                path + "/risk/acknowledgments",
                headers=HEADERS,
                json={**payload, "expected_version": version + 1},
            ).json()["code"]
            == "stale_assessment"
        )
        new = client.post(
            path + "/risk/acknowledgments",
            headers=HEADERS,
            json={
                **payload,
                "expected_version": version + 1,
                "assessment_id": updated["risk"]["assessment_id"],
            },
        )
        assert new.status_code == 200
        assert client.get(path + "/results", headers=HEADERS).json()["risk"]["level"] == "HIGH"


def test_unassessed_results_are_null_and_cannot_be_acknowledged(jobs_db):
    factory, document = jobs_db
    doc = document()
    with factory() as db:
        claim_id = db.get(Document, doc).claim_id
    with TestClient(application(factory)) as client:
        path = f"/claims/{claim_id}"
        result = client.get(path + "/results", headers=HEADERS).json()
        assert result["risk"] is None and result["risk_acknowledgment"] is None
        assert client.get(path + "/risk", headers=HEADERS).json()["items"] == []
        assert (
            client.post(
                path + "/risk/refresh", headers=HEADERS, json={"expected_version": 1}
            ).json()["code"]
            == "risk_source_unavailable"
        )


def test_cookie_csrf_and_workspace_isolation(jobs_db):
    factory, document = jobs_db
    claim_id, version, _ = completed(factory, document)
    owners = []
    try:
        with TestClient(application(factory)) as first, TestClient(application(factory)) as second:
            for client in (first, second):
                response = client.post(
                    "/auth/login",
                    headers={"Origin": ORIGIN},
                    json={"password": "risk-browser-test"},
                )
                assert response.status_code == 200
                owners.append(client.get("/auth/session").json()["actor_id"])
            with factory.begin() as db:
                db.get(Claim, claim_id).owner_id = owners[0]
            path = f"/claims/{claim_id}/risk"
            csrf = first.get("/auth/session").json()["csrf_token"]
            first_headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
            second_headers = {
                "Origin": ORIGIN,
                "X-CSRF-Token": second.get("/auth/session").json()["csrf_token"],
            }
            assert first.get(path).status_code == 200 and second.get(path).status_code == 404
            assert first.get(path, headers=HEADERS).status_code == 404
            assert (
                first.post(path + "/refresh", json={"expected_version": version}).status_code == 403
            )
            assert (
                first.post(
                    path + "/refresh",
                    headers={**first_headers, "Origin": "https://invalid.example"},
                    json={"expected_version": version},
                ).status_code
                == 403
            )
            assert (
                first.post(
                    path + "/refresh", headers=first_headers, json={"expected_version": version}
                ).status_code
                == 200
            )
            assert (
                second.post(
                    path + "/refresh", headers=second_headers, json={"expected_version": version}
                ).status_code
                == 404
            )
            first.post("/auth/logout", headers=first_headers)
            assert first.get(path).status_code == 401
    finally:
        with factory.begin() as db:
            db.execute(delete(BrowserSession).where(BrowserSession.actor_id.in_(owners)))
