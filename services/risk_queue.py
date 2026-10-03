"""Scoped latest-assessment queue, filtering/sorting/pagination in one SQL query."""

from sqlalchemy import case, func, select

from api.dependencies import APIError
from models import Claim, RiskAcknowledgment, RiskAssessment
from schema.api import ClaimResponse
from schema.risk import RiskQueueItem
from services.risk_storage import project, project_ack


def queue(db, *, level=None, acknowledged="unacknowledged", limit=20, offset=0):
    actor = db.info.get("actor_id")
    if actor is None:
        raise APIError(401, "unauthorized", "Authenticated workspace is required")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid queue pagination")
    ranked = (
        select(
            RiskAssessment.assessment_id,
            func.row_number()
            .over(
                partition_by=RiskAssessment.claim_id,
                order_by=RiskAssessment.revision.desc(),
            )
            .label("position"),
        )
        .join(Claim, Claim.claim_id == RiskAssessment.claim_id)
        .where(
            Claim.owner_id == actor,
            Claim.is_active.is_(True),
            Claim.current_state.in_(["READY", "REVIEW_REQUIRED"]),
        )
        .subquery()
    )
    ack_id = (
        select(RiskAcknowledgment.acknowledgment_id)
        .where(RiskAcknowledgment.assessment_id == RiskAssessment.assessment_id)
        .order_by(RiskAcknowledgment.created_at.desc(), RiskAcknowledgment.acknowledgment_id.desc())
        .limit(1)
        .correlate(RiskAssessment)
        .scalar_subquery()
    )
    query = (
        select(Claim, RiskAssessment, RiskAcknowledgment)
        .join(RiskAssessment, RiskAssessment.claim_id == Claim.claim_id)
        .join(ranked, ranked.c.assessment_id == RiskAssessment.assessment_id)
        .outerjoin(RiskAcknowledgment, RiskAcknowledgment.acknowledgment_id == ack_id)
        .where(ranked.c.position == 1, RiskAssessment.claim_version == Claim.version)
    )
    if level is not None:
        query = query.where(RiskAssessment.level == level)
    if acknowledged == "unacknowledged":
        query = query.where(RiskAcknowledgment.acknowledgment_id.is_(None))
    elif acknowledged == "acknowledged":
        query = query.where(RiskAcknowledgment.acknowledgment_id.is_not(None))
    elif acknowledged != "all":
        raise ValueError("Invalid acknowledgment filter")
    priority = case(
        {"HIGH": 0, "MEDIUM": 1, "INSUFFICIENT_DATA": 2, "LOW": 3},
        value=RiskAssessment.level,
        else_=4,
    )
    rows = db.execute(
        query.order_by(priority, RiskAssessment.assessed_at, Claim.claim_id)
        .limit(limit)
        .offset(offset)
    )
    return [
        RiskQueueItem(
            claim=ClaimResponse.model_validate(claim),
            risk=project(assessment),
            acknowledgment=project_ack(ack) if ack else None,
        )
        for claim, assessment, ack in rows
    ]
