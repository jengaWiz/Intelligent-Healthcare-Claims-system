"""Enqueue commits before returning; HTTP requests never run provider work."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from api.dependencies import APIError, get_api_db, require_token
from models import Document, ProcessingJob
from schema.api import ErrorResponse, JobResponse
from services.access_service import owns
from services.job_service import JobError, enqueue

router = APIRouter(
    dependencies=[Depends(require_token)],
    responses={status: {"model": ErrorResponse} for status in (401, 404, 409, 422, 503)},
)


@router.post(
    "/documents/{document_id}/extract",
    status_code=202,
    response_model=JobResponse,
    responses={
        202: {
            "headers": {
                "Location": {"schema": {"type": "string"}},
                "Retry-After": {"schema": {"type": "integer", "minimum": 1}},
            }
        }
    },
)
def enqueue_document(
    document_id: UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_api_db),
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None,
):
    try:
        with db.begin():
            document = db.get(Document, document_id)
            if document is not None and not owns(db, document.claim):
                raise APIError(404, "document_not_found", "Document not found")
            job = enqueue(db, document_id, request.app.state.settings, key)
            result = JobResponse.model_validate(job)
    except JobError as exc:
        raise APIError(exc.status, exc.code, exc.message) from None
    response.headers["Location"] = f"/jobs/{result.job_id}"
    response.headers["Retry-After"] = "2"
    return result


@router.get("/jobs/{job_id}", response_model=JobResponse)
def read_job(job_id: UUID, db: Session = Depends(get_api_db)):
    job = db.get(ProcessingJob, job_id)
    if job is None or not owns(db, job.document.claim):
        raise APIError(404, "job_not_found", "Job not found")
    return JobResponse.model_validate(job)
