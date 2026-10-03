"""Immutable extraction evidence, append-only revisions, and serialized decisions."""

from sqlalchemy import select

from agents.validation_agent import ValidationAgent
from api.dependencies import APIError
from models import Document, ExtractionResult, ProcessingJob, Review
from schema.api import ClaimResponse, JobResponse
from schema.claim_data import ClaimData
from schema.validation_result import ValidationResult
from services import risk_storage
from services.claim_service import get_claim
from services.risk_assessment_service import publish


def extraction(db, claim_id):
    return db.scalar(
        select(ExtractionResult)
        .join(Document, ExtractionResult.document_id == Document.document_id)
        .where(Document.claim_id == claim_id)
    )


def history(db, claim_id):
    return db.scalars(
        select(Review).where(Review.claim_id == claim_id).order_by(Review.new_version)
    ).all()


def audit_projection(review):
    return {
        "review_id": review.review_id,
        "actor_id": review.actor_id,
        "decision": review.decision,
        "reason": review.reason,
        "previous_version": review.previous_version,
        "new_version": review.new_version,
        "before_data": review.before_data,
        "after_data": review.after_data,
        "created_at": review.created_at,
    }


def result_projection(db, claim_id):
    claim = get_claim(db, claim_id)
    result = extraction(db, claim_id)
    job = db.scalar(
        select(ProcessingJob)
        .join(Document, ProcessingJob.document_id == Document.document_id)
        .where(Document.claim_id == claim_id)
        .order_by(ProcessingJob.created_at.desc(), ProcessingJob.job_id.desc())
        .limit(1)
    )
    reviews = history(db, claim_id)
    risk = risk_storage.current(db, claim_id)
    snapshot = None
    if result:
        snapshot = {
            "data": result.normalized_data,
            "validation": {
                key: getattr(result.validation, key)
                for key in (
                    "is_valid",
                    "validation_score",
                    "semantic_status",
                    "issues",
                    "recommendations",
                )
            },
        }
    return {
        "claim": ClaimResponse.model_validate(claim),
        "job": JobResponse.model_validate(job) if job else None,
        "extraction": {
            "extraction_id": result.extraction_id,
            "engine": result.extraction_engine,
            "version": result.extraction_version,
            "original_data": result.normalized_data,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "outcome": result.outcome,
            "provenance": result.provenance,
            "created_at": result.created_at,
        }
        if result
        else None,
        "current": reviews[-1].after_data if reviews else snapshot,
        "reviews": [audit_projection(review) for review in reviews],
        "risk": risk,
        "risk_acknowledgment": risk_storage.current_ack(db, risk),
    }


def decide(db, claim_id, payload, actor):
    claim = get_claim(db, claim_id, lock=True)
    if claim.version != payload.expected_version:
        raise APIError(409, "stale_review", "Claim changed; refresh before reviewing")
    if claim.current_state != "REVIEW_REQUIRED":
        raise APIError(409, "review_conflict", "Only review-required records accept decisions")
    result = extraction(db, claim_id)
    if result is None:
        raise APIError(409, "result_unavailable", "Extraction result is unavailable")
    before = result_projection(db, claim_id)["current"]
    data = (
        payload.corrections.apply(before["data"])
        if payload.corrections
        else ClaimData.model_validate(before["data"])
    )
    # Human review replaces semantic/low-confidence gating, but cannot bypass critical rules.
    validator = ValidationAgent()
    issues = [
        *validator._check_missing_fields(data),
        *validator._check_date_logic(data),
        *validator._check_amounts(data),
    ]
    validation = ValidationResult(
        is_valid=not any(issue.severity == "critical" for issue in issues),
        validation_score=validator._calculate_score(issues),
        semantic_status="unavailable",
        issues=issues,
        recommendations=["Human document-data review recorded; no payer or payment decision"],
    )
    if payload.decision != "reject" and not validation.is_valid:
        raise APIError(422, "invalid_correction", "Resolve critical data issues before accepting")
    after = {
        "data": data.model_dump(mode="json"),
        "validation": validation.model_dump(mode="json"),
        "human_reviewed": True,
    }
    review = Review(
        claim_id=claim_id,
        actor_id=actor,
        decision=payload.decision,
        reason=payload.reason,
        previous_version=claim.version,
        new_version=claim.version + 1,
        before_data=before,
        after_data=after,
    )
    db.add(review)
    claim.version += 1
    claim.current_state = "REJECTED" if payload.decision == "reject" else "READY"
    db.flush()
    publish(db, claim, result, data, validation, human_verified=True)
    return result_projection(db, claim_id)
