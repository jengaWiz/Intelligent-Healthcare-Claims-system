"""Mounted contract placeholders until bounded uploads and durable jobs are implemented."""

from uuid import UUID

from fastapi import APIRouter, Depends

from api.dependencies import APIError, require_token
from schema.api import ErrorResponse

router = APIRouter(
    dependencies=[Depends(require_token)],
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        501: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


@router.post("/claims/{claim_id}/documents", status_code=501, response_model=ErrorResponse)
def upload_document(claim_id: UUID):
    raise APIError(501, "upload_not_implemented", "Document upload is not implemented yet")


@router.post("/documents/{document_id}/extract", status_code=501, response_model=ErrorResponse)
def extract_document(document_id: UUID):
    raise APIError(501, "extraction_not_implemented", "Document processing is not implemented yet")
