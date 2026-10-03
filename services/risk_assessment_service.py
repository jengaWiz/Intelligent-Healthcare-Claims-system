"""Assessment integration with explicit clock/context and atomic caller transaction."""

from sqlalchemy import func, select

from api.dependencies import APIError
from models import Document, ExtractionResult, Review
from schema.claim_data import ClaimData
from schema.review import Snapshot
from schema.validation_result import ValidationResult
from services import risk_storage
from services.claim_service import get_claim
from services.risk_engine import RiskContext, assess, fingerprint, load_policy


def context_for(db, claim, document_id):
    # RT06 supplies the ownership-scoped peer snapshot. Never imply a completed
    # duplicate scan before that integration is present.
    return RiskContext(
        duplicate_count=0,
        complete=False,
        fingerprint=fingerprint({"duplicate_context": "unavailable"}),
        captured_at=db.scalar(select(func.clock_timestamp())),
    )


def publish(db, claim, extraction, data, validation, *, human_verified=False):
    # The stored extraction confidence is authoritative even if a normalized
    # snapshot carries older or inconsistent extraction metadata.
    data = data.model_copy(update={"extraction_confidence": extraction.confidence})
    context = context_for(db, claim, extraction.document_id)
    evaluation = assess(
        data,
        validation,
        human_verified=human_verified,
        context=context,
        assessed_at=db.scalar(select(func.clock_timestamp())),
        policy=load_policy(),
    )
    return risk_storage.store(
        db,
        claim.claim_id,
        extraction.extraction_id,
        evaluation,
        expected_version=claim.version,
    )


def refresh(db, claim_id, payload):
    claim = get_claim(db, claim_id, lock=True)
    if claim.version != payload.expected_version:
        raise APIError(409, "stale_risk", "Claim changed; refresh before assessing")
    if not claim.is_active or claim.current_state == "REJECTED":
        raise APIError(409, "risk_inactive", "Inactive claims cannot be reassessed")
    source = db.scalar(select(ExtractionResult).join(Document).where(Document.claim_id == claim_id))
    if source is None or claim.current_state not in {"READY", "REVIEW_REQUIRED"}:
        raise APIError(409, "risk_source_unavailable", "Current extraction result is unavailable")
    review = db.scalar(
        select(Review)
        .where(Review.claim_id == claim_id)
        .order_by(Review.new_version.desc())
        .limit(1)
    )
    if review:
        if review.new_version != claim.version:
            raise APIError(409, "risk_source_unavailable", "Current reviewed data is unavailable")
        snapshot = Snapshot.model_validate(review.after_data)
        data, validation, human = snapshot.data, snapshot.validation, snapshot.human_reviewed
    else:
        data = ClaimData.model_validate(source.normalized_data)
        validation = ValidationResult.model_validate(
            {field: getattr(source.validation, field) for field in ValidationResult.model_fields}
        )
        human = False
    return publish(db, claim, source, data, validation, human_verified=human)
