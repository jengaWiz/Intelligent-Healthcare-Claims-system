"""Queue is independent of document quality and paginated/scoped in SQL."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from config.settings import Settings
from models import Claim, Document, ExtractionResult
from schema.review import ReviewCreate
from services.review_service import decide
from tests.integration.test_jobs import jobs_db as _jobs_db
from tests.integration.test_reviews import completed

jobs_db = _jobs_db
pytestmark = pytest.mark.integration
HEADERS = {"Authorization": "Bearer risk-queue-test"}


def test_priority_filters_pagination_and_new_assessment_reappearance(jobs_db):
    factory, document = jobs_db
    ids = []
    for index, amount in enumerate(("42.50", "10001", "100001", None)):
        claim_id, version, extraction_id = completed(factory, document)
        ids.append(claim_id)
        with factory.begin() as db:
            result = db.get(ExtractionResult, extraction_id)
            db.get(Document, result.document_id).sha256 = f"{index + 1:064x}"
            db.flush()
            if amount is not None:
                decide(
                    db,
                    claim_id,
                    ReviewCreate(
                        expected_version=version,
                        decision="correct",
                        reason="Synthetic policy scenario",
                        corrections={
                            "patient_name": "Synthetic",
                            "provider_name": "Clinic",
                            "service_date": "2026-10-01",
                            "total_amount": amount,
                        },
                    ),
                    "api",
                )
    with TestClient(
        create_app(
            Settings(_env_file=None, api_auth_token="risk-queue-test"), session_factory=factory
        )
    ) as client:
        response = client.get("/risk/queue", headers=HEADERS)
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [item["risk"]["level"] for item in items] == [
            "HIGH",
            "MEDIUM",
            "INSUFFICIENT_DATA",
            "LOW",
        ]
        expected = [item["claim"]["claim_id"] for item in items]
        pages = []
        for offset in (0, 2):
            pages += client.get(f"/risk/queue?limit=2&offset={offset}", headers=HEADERS).json()[
                "items"
            ]
        assert [item["claim"]["claim_id"] for item in pages] == expected
        assert len(client.get("/risk/queue?level=HIGH", headers=HEADERS).json()["items"]) == 1
        for params in (
            {"level": "FRAUD"},
            {"acknowledged": "unknown"},
            {"limit": 101},
            {"offset": -1},
        ):
            assert client.get("/risk/queue", headers=HEADERS, params=params).status_code == 422
        high = items[0]
        claim_id = high["claim"]["claim_id"]
        payload = {
            "expected_version": high["claim"]["version"],
            "assessment_id": high["risk"]["assessment_id"],
            "reason": "Investigated",
        }
        assert (
            client.post(
                f"/claims/{claim_id}/risk/acknowledgments", headers=HEADERS, json=payload
            ).status_code
            == 200
        )
        assert len(client.get("/risk/queue", headers=HEADERS).json()["items"]) == 3
        assert (
            len(
                client.get("/risk/queue?acknowledged=acknowledged", headers=HEADERS).json()["items"]
            )
            == 1
        )
        assert len(client.get("/risk/queue?acknowledged=all", headers=HEADERS).json()["items"]) == 4
        with factory.begin() as db:
            source_doc = db.get(Claim, ids[2]).documents[0]
            matching_sha = source_doc.sha256
        peer = document()
        with factory.begin() as db:
            db.get(Document, peer).sha256 = matching_sha
        refreshed = client.post(
            f"/claims/{claim_id}/risk/refresh",
            headers=HEADERS,
            json={"expected_version": payload["expected_version"]},
        )
        assert refreshed.status_code == 200
        assert len(client.get("/risk/queue", headers=HEADERS).json()["items"]) == 4
        assert len(client.get("/claims", headers=HEADERS).json()) == 5


def test_queue_excludes_legacy_rejected_inactive_stale_and_other_owner(jobs_db):
    factory, document = jobs_db
    rows = [completed(factory, document) for _ in range(4)]
    with factory.begin() as db:
        db.get(Claim, rows[0][0]).is_active = False
        decide(
            db,
            rows[1][0],
            ReviewCreate(
                expected_version=rows[1][1], decision="reject", reason="Synthetic rejection"
            ),
            "api",
        )
        db.get(Claim, rows[2][0]).owner_id = "other-workspace"
        db.get(Claim, rows[3][0]).version += 1
    document()
    with TestClient(
        create_app(
            Settings(_env_file=None, api_auth_token="risk-queue-test"), session_factory=factory
        )
    ) as client:
        assert client.get("/risk/queue").status_code == 401
        assert client.get("/risk/queue?acknowledged=all", headers=HEADERS).json()["items"] == []
        assert len(client.get("/claims", headers=HEADERS).json()) == 4
