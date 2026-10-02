"""Bounded synthetic uploads; durable extraction remains a separate ticket."""

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from api.dependencies import APIError, get_api_db, require_token
from models import Document
from schema.api import DocumentResponse, ErrorResponse
from services.document_service import (
    ClaimNotFound,
    DocumentConflict,
    create_document,
    verify_upload_claim,
)
from services.storage_service import StorageError, delete_file, save_file

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[Depends(require_token)],
    responses={status: {"model": ErrorResponse} for status in (401, 404, 409, 413, 415, 422, 503)},
)
CHUNK_BYTES = 64 * 1024
SIGNATURES = {
    "application/pdf": b"%PDF-",
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
}


def claim_error(exc):
    if isinstance(exc, ClaimNotFound):
        return APIError(404, "claim_not_found", "Claim not found")
    return APIError(409, "document_conflict", "Claim already has a document or is processing")


async def read_file(file, limit):
    name = file.filename or ""
    if (
        not name
        or len(name) > 225
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise APIError(
            422, "invalid_filename", "A simple filename of at most 225 characters is required"
        )
    mime = (file.content_type or "").split(";", 1)[0].strip().lower()
    if mime not in SIGNATURES:
        raise APIError(415, "unsupported_file", "Only PDF, JPEG and PNG documents are supported")
    data = bytearray()
    while True:
        chunk = await file.read(min(CHUNK_BYTES, limit - len(data) + 1))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise APIError(413, "file_too_large", "Document exceeds the configured size limit")
    if not data:
        raise APIError(422, "empty_file", "Document must not be empty")
    if not data.startswith(SIGNATURES[mime]):
        raise APIError(415, "content_mismatch", "Document content does not match its declared type")
    return name, mime, bytes(data)


@router.post(
    "/claims/{claim_id}/documents",
    status_code=201,
    response_model=DocumentResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "additionalProperties": False,
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def upload_document(
    claim_id: UUID, request: Request, response: Response, db: Session = Depends(get_api_db)
):
    settings = request.app.state.settings

    def initial_check():
        with db.begin():
            verify_upload_claim(db, claim_id)

    try:
        await run_in_threadpool(initial_check)
    except (ClaimNotFound, DocumentConflict) as exc:
        raise claim_error(exc) from None

    try:
        async with request.form(
            max_files=1, max_fields=0, max_part_size=settings.max_upload_bytes
        ) as form:
            file = form.get("file")
            if len(form) != 1 or not isinstance(file, UploadFile):
                raise APIError(
                    422, "invalid_upload", "Exactly one file field named file is required"
                )
            name, mime, content = await read_file(file, settings.max_upload_bytes)
    except HTTPException:
        if getattr(request.state, "upload_request_too_large", False):
            raise APIError(
                413, "request_too_large", "Upload request exceeds the configured limit"
            ) from None
        raise APIError(422, "invalid_upload", "Upload multipart data is invalid") from None

    def persist():
        path = None
        committing = False
        result = None
        try:
            with db.begin():
                # Lock/recheck after body parsing; do not hold locks while waiting on client traffic.
                verify_upload_claim(db, claim_id, lock=True)
                path = save_file(content, mime, settings.upload_dir)
                doc = create_document(db, claim_id, name, mime, content, path)
                result = DocumentResponse.model_validate(doc)
                committing = True
            return result
        except Exception:
            if path is not None and committing:
                try:
                    with request.app.state.get_session_factory()() as confirmation:
                        persisted = confirmation.get(Document, result.document_id)
                        if persisted is not None:
                            # A lost commit acknowledgement must not delete a committed file.
                            return DocumentResponse.model_validate(persisted)
                except Exception:
                    logger.error(
                        "Upload commit status unknown; document_id=%s request_id=%s",
                        result.document_id,
                        request.state.request_id,
                    )
                    raise APIError(
                        503,
                        "upload_status_unknown",
                        "Upload status needs confirmation; retain the claim ID",
                    ) from None
            if path is not None:
                try:
                    delete_file(path, settings.upload_dir)
                except (OSError, StorageError):
                    logger.error(
                        "Upload cleanup failed; storage_name=%s request_id=%s",
                        Path(path).name,
                        request.state.request_id,
                    )
                    raise APIError(
                        503,
                        "cleanup_failed",
                        "Upload could not be completed; cleanup needs attention",
                    ) from None
            raise

    try:
        result = await run_in_threadpool(persist)
    except (ClaimNotFound, DocumentConflict) as exc:
        raise claim_error(exc) from None
    except IntegrityError:
        raise APIError(409, "document_conflict", "Document could not be accepted") from None
    except (OSError, StorageError):
        raise APIError(503, "storage_unavailable", "Upload storage is unavailable") from None
    response.headers["Location"] = f"/documents/{result.document_id}"
    return result


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def read_document(document_id: UUID, db: Session = Depends(get_api_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise APIError(404, "document_not_found", "Document not found")
    return DocumentResponse.model_validate(document)
