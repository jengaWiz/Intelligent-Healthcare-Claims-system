"""Claim-serialized append-only storage; callers own commit and rollback."""

from datetime import UTC

from sqlalchemy import select

from api.dependencies import APIError
from models import Document, ExtractionResult, RiskAcknowledgment, RiskAssessment
from schema.risk import RiskAcknowledgmentResponse, RiskAssessmentResponse, RiskEvaluation
from services.review_service import get_claim


def latest(db, claim_id):
    return db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.claim_id == claim_id)
        .order_by(RiskAssessment.revision.desc())
        .limit(1)
    )


def project(assessment):
    values = {key: getattr(assessment, key) for key in RiskAssessmentResponse.model_fields}
    for key in ("assessed_at", "context_at"):
        value = values[key]
        values[key] = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return RiskAssessmentResponse.model_validate(values)


def current(db, claim_id):
    claim = get_claim(db, claim_id)
    item = latest(db, claim_id)
    return project(item) if item and item.claim_version == claim.version else None


def history(db, claim_id, *, limit=20, offset=0):
    get_claim(db, claim_id)
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid history pagination")
    return [
        project(item)
        for item in db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.claim_id == claim_id)
            .order_by(RiskAssessment.revision.desc())
            .limit(limit)
            .offset(offset)
        )
    ]


def store(db, claim_id, extraction_id, evaluation, *, expected_version):
    claim = get_claim(db, claim_id, lock=True)
    if claim.version != expected_version:
        raise APIError(409, "stale_risk", "Claim changed; refresh before assessing")
    source = db.scalar(
        select(ExtractionResult)
        .join(Document)
        .where(ExtractionResult.extraction_id == extraction_id, Document.claim_id == claim_id)
    )
    if source is None:
        raise APIError(409, "risk_source_unavailable", "Extraction result is unavailable")
    evaluation = RiskEvaluation.model_validate(evaluation.model_dump())
    previous = latest(db, claim_id)
    if previous and (
        previous.claim_version == expected_version
        and previous.extraction_id == extraction_id
        and previous.policy_version == evaluation.policy_version
        and previous.input_fingerprint == evaluation.input_fingerprint
        and previous.context_fingerprint == evaluation.context_fingerprint
    ):
        return previous
    item = RiskAssessment(
        claim_id=claim_id,
        document_id=source.document_id,
        extraction_id=extraction_id,
        claim_version=expected_version,
        revision=previous.revision + 1 if previous else 1,
        **evaluation.model_dump(mode="json", exclude={"assessed_at", "context_at"}),
        assessed_at=evaluation.assessed_at,
        context_at=evaluation.context_at,
    )
    db.add(item)
    db.flush()
    return item


def acknowledge(db, claim_id, payload, actor):
    claim = get_claim(db, claim_id, lock=True)
    if claim.version != payload.expected_version:
        raise APIError(409, "stale_risk", "Claim changed; refresh before acknowledging")
    if not claim.is_active or claim.current_state == "REJECTED":
        raise APIError(409, "risk_inactive", "Inactive claims cannot be acknowledged")
    item = latest(db, claim_id)
    if (
        item is None
        or item.claim_version != claim.version
        or item.assessment_id != payload.assessment_id
    ):
        raise APIError(409, "stale_assessment", "Refresh the current risk assessment")
    if db.info.get("actor_id", actor) != actor:
        raise APIError(403, "actor_mismatch", "Acknowledgment actor does not match session")
    existing = db.scalar(
        select(RiskAcknowledgment).where(
            RiskAcknowledgment.assessment_id == item.assessment_id,
            RiskAcknowledgment.actor_id == actor,
        )
    )
    if existing:
        if existing.reason != payload.reason:
            raise APIError(409, "risk_already_acknowledged", "An acknowledgment already exists")
        return existing
    record = RiskAcknowledgment(
        assessment_id=item.assessment_id, actor_id=actor, reason=payload.reason
    )
    db.add(record)
    db.flush()
    return record


def project_ack(record):
    value = record.created_at
    return RiskAcknowledgmentResponse(
        acknowledgment_id=record.acknowledgment_id,
        assessment_id=record.assessment_id,
        actor_id=record.actor_id,
        reason=record.reason,
        created_at=value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC),
    )
