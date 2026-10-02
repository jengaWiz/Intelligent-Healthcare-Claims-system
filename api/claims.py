from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_api_db, require_token
from models import Claim
from schema.api import ClaimCreate, ClaimResponse, ErrorResponse
from services.access_service import scoped
from services.claim_service import create_claim
from services.review_service import get_claim

router = APIRouter(
    dependencies=[Depends(require_token)],
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)


@router.post("/claims", response_model=ClaimResponse, status_code=201)
def post_claim(payload: ClaimCreate, response: Response, db: Session = Depends(get_api_db)):
    with db.begin():
        claim = create_claim(db, payload.source_system)
        result = ClaimResponse.model_validate(claim)
    response.headers["Location"] = f"/claims/{result.claim_id}"
    return result


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def read_claim(claim_id: UUID, db: Session = Depends(get_api_db)):
    claim = get_claim(db, claim_id)
    return ClaimResponse.model_validate(claim)


@router.get("/claims", response_model=list[ClaimResponse])
def list_claims(
    db: Session = Depends(get_api_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return db.scalars(
        scoped(select(Claim), db)
        .order_by(Claim.created_at.desc(), Claim.claim_id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
