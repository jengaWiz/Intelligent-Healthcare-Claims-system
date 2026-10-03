"""Risk review is independent of document approval, protected by existing access."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from api.dependencies import get_api_db, require_token
from schema.risk import (
    RiskAcknowledgmentCreate,
    RiskAcknowledgmentResponse,
    RiskAssessmentResponse,
    RiskHistoryResponse,
    RiskLevel,
    RiskQueueResponse,
    RiskRefreshCreate,
)
from services import risk_storage
from services.risk_assessment_service import refresh
from services.risk_queue import queue

router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/risk/queue", response_model=RiskQueueResponse)
def risk_queue(
    db: Session = Depends(get_api_db),
    level: RiskLevel | None = Query(None),
    acknowledged: Literal["all", "acknowledged", "unacknowledged"] = Query("unacknowledged"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return RiskQueueResponse(
        items=queue(db, level=level, acknowledged=acknowledged, limit=limit, offset=offset),
        limit=limit,
        offset=offset,
    )


@router.get("/claims/{claim_id}/risk", response_model=RiskHistoryResponse)
def history(
    claim_id: UUID,
    db: Session = Depends(get_api_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return RiskHistoryResponse(
        items=risk_storage.history(db, claim_id, limit=limit, offset=offset),
        limit=limit,
        offset=offset,
    )


@router.post("/claims/{claim_id}/risk/refresh", response_model=RiskAssessmentResponse)
def post_refresh(claim_id: UUID, payload: RiskRefreshCreate, db: Session = Depends(get_api_db)):
    with db.begin():
        item = risk_storage.project(refresh(db, claim_id, payload))
    return item


@router.post("/claims/{claim_id}/risk/acknowledgments", response_model=RiskAcknowledgmentResponse)
def acknowledge(
    claim_id: UUID,
    payload: RiskAcknowledgmentCreate,
    request: Request,
    db: Session = Depends(get_api_db),
):
    with db.begin():
        record = risk_storage.acknowledge(db, claim_id, payload, request.state.actor_id)
        response = risk_storage.project_ack(record)
    return response
