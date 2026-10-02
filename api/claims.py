from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api.dependencies import APIError, get_api_db, require_token
from models import Claim
from schema.api import ClaimCreate, ClaimResponse, ErrorResponse
from services.claim_service import create_claim

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
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise APIError(404, "claim_not_found", "Claim not found")
    return ClaimResponse.model_validate(claim)
