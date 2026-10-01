import hashlib
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import create_app
from config.settings import Settings
from models import Claim, Document
from services.document_service import create_document

TOKEN = "synthetic-upload-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SAMPLES = [
    ("sample.pdf", "application/pdf", b"%PDF-1.7\nsynthetic"),
    ("sample.jpg", "image/jpeg", b"\xff\xd8\xffsynthetic"),
    ("sample.png", "image/png", b"\x89PNG\r\n\x1a\nsynthetic"),
]


@pytest.fixture
def upload_api(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Claim.__table__.create(engine)
    Document.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    settings = Settings(
        _env_file=None, api_auth_token=TOKEN, upload_dir=tmp_path / "uploads", max_upload_bytes=64
    )
    app = create_app(settings, session_factory=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        claim = client.post("/claims", headers=HEADERS, json={}).json()["claim_id"]
        yield client, factory, settings, claim
    engine.dispose()


def upload(client, claim, name="sample.pdf", content=b"%PDF-1.7 synthetic", mime="application/pdf"):
    return client.post(
        f"/claims/{claim}/documents", headers=HEADERS, files={"file": (name, content, mime)}
    )


def no_artifacts(factory, settings):
    assert not settings.upload_dir.exists() or list(settings.upload_dir.iterdir()) == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


@pytest.mark.parametrize("name,mime,content", SAMPLES)
def test_upload_and_read_metadata(upload_api, name, mime, content):
    client, factory, settings, claim = upload_api
    response = upload(client, claim, name, content, mime)
    assert response.status_code == 201, response.text
    metadata = response.json()
    assert metadata["mime_type"] == mime and metadata["state"] == "UPLOADED"
    assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
    assert metadata["byte_size"] == len(content) and metadata["file_name"] == name
    assert "storage_path" not in metadata and str(settings.upload_dir) not in response.text
    assert client.get(response.headers["location"], headers=HEADERS).json() == metadata
    with factory() as db:
        doc = db.get(Document, UUID(metadata["document_id"]))
        path = Path(doc.storage_path)
        assert path.parent == settings.upload_dir.resolve()
        assert path.name != name and name not in path.name
        assert path.read_bytes() == content
        assert path.stat().st_mode & 0o777 == 0o600
    # A separate app instance reuses the durable directory and DB, not process memory.
    with TestClient(create_app(settings, session_factory=factory)) as restarted:
        assert restarted.get(response.headers["location"], headers=HEADERS).json() == metadata
        assert path.read_bytes() == content


@pytest.mark.parametrize(
    "name,content,mime,status",
    [
        ("sample.pdf", b"", "application/pdf", 422),
        ("sample.pdf", b"%PDF-" + b"x" * 60, "application/pdf", 413),
        ("sample.pdf", b"not a PDF", "application/pdf", 415),
        ("sample.png", b"%PDF-synthetic", "image/png", 415),
        ("sample.txt", b"%PDF-synthetic", "text/plain", 415),
        ("../escape.pdf", b"%PDF-synthetic", "application/pdf", 422),
        ("x" * 226, b"%PDF-synthetic", "application/pdf", 422),
    ],
)
def test_rejected_files_leave_no_artifacts(upload_api, name, content, mime, status):
    client, factory, settings, claim = upload_api
    assert upload(client, claim, name, content, mime).status_code == status
    no_artifacts(factory, settings)


def test_exact_limit_and_duplicate_claim(upload_api):
    client, factory, settings, claim = upload_api
    assert upload(client, claim, content=b"%PDF-" + b"x" * 59).status_code == 201
    paths = list(settings.upload_dir.iterdir())
    assert upload(client, claim).status_code == 409
    assert list(settings.upload_dir.iterdir()) == paths
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 1


def test_missing_claim_checked_before_storage(upload_api):
    client, factory, settings, _ = upload_api
    with patch("api.documents.save_file") as save:
        assert upload(client, str(uuid4())).status_code == 404
        save.assert_not_called()
    no_artifacts(factory, settings)


def test_malformed_or_multiple_parts(upload_api):
    client, factory, settings, claim = upload_api
    cases = [
        {"wrong": ("a.pdf", b"%PDF-synthetic", "application/pdf")},
        [
            ("file", ("a.pdf", b"%PDF-a", "application/pdf")),
            ("file", ("b.pdf", b"%PDF-b", "application/pdf")),
        ],
    ]
    for files in cases:
        response = client.post(f"/claims/{claim}/documents", headers=HEADERS, files=files)
        assert response.status_code == 422
    response = client.post(f"/claims/{claim}/documents", headers=HEADERS, json={})
    assert response.status_code == 422
    no_artifacts(factory, settings)


def test_chunked_request_budget_without_content_length(upload_api):
    client, factory, settings, claim = upload_api
    prefix = b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-'
    chunks = iter([prefix, b"x" * (64 * 1024 + 100), b"\r\n--boundary--\r\n"])
    response = client.post(
        f"/claims/{claim}/documents",
        headers={**HEADERS, "Content-Type": "multipart/form-data; boundary=boundary"},
        content=chunks,
    )
    assert response.status_code == 413, response.text
    no_artifacts(factory, settings)


def test_claim_deleted_between_initial_check_and_save(upload_api):
    client, factory, settings, claim = upload_api
    from api.documents import read_file

    async def delete_after_read(file, limit):
        result = await read_file(file, limit)
        with factory.begin() as db:
            db.delete(db.get(Claim, UUID(claim)))
        return result

    with patch("api.documents.read_file", side_effect=delete_after_read):
        assert upload(client, claim).status_code == 404
    no_artifacts(factory, settings)


def test_storage_write_failure_cleans_temporary_file(upload_api):
    client, factory, settings, claim = upload_api
    with patch("services.storage_service.os.replace", side_effect=PermissionError("synthetic")):
        response = upload(client, claim)
    assert response.status_code == 503
    no_artifacts(factory, settings)


def test_flush_failure_removes_stored_file(upload_api):
    client, factory, settings, claim = upload_api

    def fail_after_flush(*args, **kwargs):
        create_document(*args, **kwargs)
        raise OperationalError("INSERT", {}, RuntimeError("synthetic secret"))

    with patch("api.documents.create_document", side_effect=fail_after_flush):
        response = upload(client, claim)
    assert response.status_code == 503 and "synthetic secret" not in response.text
    no_artifacts(factory, settings)


def commit_hooks(factory, mode):
    def track(db, context, instances):
        if any(isinstance(item, Document) for item in db.new):
            db.info["upload_commit"] = True

    def fail(db):
        if db.info.get("upload_commit"):
            raise OperationalError("COMMIT", {}, RuntimeError("synthetic connection lost"))

    event.listen(factory, "before_flush", track)
    event.listen(factory, mode, fail)


def test_commit_failure_rolls_back_and_cleans(upload_api):
    client, factory, settings, claim = upload_api
    commit_hooks(factory, "before_commit")
    assert upload(client, claim).status_code == 503
    no_artifacts(factory, settings)


def test_lost_commit_acknowledgement_preserves_committed_file(upload_api):
    client, factory, settings, claim = upload_api
    commit_hooks(factory, "after_commit")
    response = upload(client, claim)
    assert response.status_code == 201, response.text
    assert client.get(response.headers["location"], headers=HEADERS).status_code == 200
    assert len(list(settings.upload_dir.iterdir())) == 1


def test_cleanup_failure_is_reported(upload_api):
    client, factory, settings, claim = upload_api
    with patch("api.documents.create_document", side_effect=RuntimeError("synthetic failure")):
        with patch("api.documents.delete_file", side_effect=PermissionError("synthetic cleanup")):
            response = upload(client, claim)
    assert response.status_code == 503 and response.json()["code"] == "cleanup_failed"
    # Unremovable files require explicit operator attention, not a false cleanup claim.
    assert len(list(settings.upload_dir.iterdir())) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_document_lookup_missing_id_and_auth(upload_api):
    client, _, _, _ = upload_api
    assert client.get(f"/documents/{uuid4()}", headers=HEADERS).status_code == 404
    assert client.get("/documents/invalid", headers=HEADERS).status_code == 422
    assert client.get(f"/documents/{uuid4()}").status_code == 401


def test_windows_client_path_is_normalized_and_never_used_for_storage(upload_api):
    client, factory, settings, claim = upload_api
    response = upload(client, claim, name="C:\\escape.pdf")
    assert response.status_code == 201
    assert response.json()["file_name"] == "escape.pdf"
    with factory() as db:
        path = Path(db.get(Document, UUID(response.json()["document_id"])).storage_path)
        assert path.parent == settings.upload_dir.resolve()
        assert "escape" not in path.name


def test_unconfirmed_commit_preserves_file_for_reconciliation(upload_api):
    client, factory, settings, claim = upload_api
    commit_hooks(factory, "before_commit")
    original = client.app.state.get_session_factory
    calls = 0

    def unavailable_on_confirmation():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OperationalError("CONNECT", {}, RuntimeError("synthetic unavailable"))
        return original()

    client.app.state.get_session_factory = unavailable_on_confirmation
    response = upload(client, claim)
    assert response.status_code == 503
    assert response.json()["code"] == "upload_status_unknown"
    assert len(list(settings.upload_dir.iterdir())) == 1
