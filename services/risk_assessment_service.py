"""Assessment integration with explicit clock/context and atomic caller transaction."""

from sqlalchemy import func, select

from services import risk_storage
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
