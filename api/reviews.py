"""Persisted results and explicit human document-data review."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_api_db, require_token
from models import Claim
from schema.api import ClaimResponse
from schema.review import AuditResponse, ResultsResponse, ReviewCreate
from services.review_service import audit_projection, decide, get_claim, history, result_projection

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/claims/{claim_id}/results", response_model=ResultsResponse)
def read_results(claim_id: UUID, db: Session = Depends(get_api_db)):
    return result_projection(db, claim_id)


@router.get("/reviews", response_model=list[ClaimResponse])
def queue(
    db: Session = Depends(get_api_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return db.scalars(
        select(Claim)
        .where(Claim.current_state == "REVIEW_REQUIRED")
        .order_by(Claim.created_at, Claim.claim_id)
        .limit(limit)
        .offset(offset)
    ).all()


@router.get("/claims/{claim_id}/reviews", response_model=list[AuditResponse])
def read_reviews(claim_id: UUID, db: Session = Depends(get_api_db)):
    get_claim(db, claim_id)
    return [audit_projection(review) for review in history(db, claim_id)]


@router.post("/claims/{claim_id}/reviews", response_model=ResultsResponse)
def post_review(
    claim_id: UUID, payload: ReviewCreate, request: Request, db: Session = Depends(get_api_db)
):
    with db.begin():
        result = decide(db, claim_id, payload, getattr(request.state, "actor_id", "api"))
    return result
