"""Exact-document context is always explicitly scoped, including worker sessions."""

import hashlib

from sqlalchemy import func, select

from api.dependencies import APIError
from models import Claim, Document
from services.risk_engine import RiskContext


def peer_query(claim, document):
    return (
        select(Claim.claim_id)
        .join(Document, Document.claim_id == Claim.claim_id)
        .where(
            Claim.owner_id == claim.owner_id,
            Claim.is_active.is_(True),
            Claim.current_state != "REJECTED",
            Claim.claim_id != claim.claim_id,
            Document.sha256 == document.sha256,
        )
        .order_by(Claim.claim_id)
    )


def context_for(db, claim, document_id):
    document = db.scalar(
        select(Document).where(
            Document.document_id == document_id,
            Document.claim_id == claim.claim_id,
        )
    )
    if document is None:
        raise APIError(409, "risk_source_unavailable", "Source document is unavailable")
    captured_at = db.scalar(select(func.clock_timestamp()))
    digest = hashlib.sha256()
    digest.update(b"risk-document-context-v1\0")
    digest.update(document.sha256.encode())
    count = 0
    # Stream IDs in deterministic order: no peer values/identities enter public
    # evidence, and memory stays bounded even with many matching documents.
    for peer_id in db.scalars(peer_query(claim, document).execution_options(yield_per=100)):
        digest.update(peer_id.bytes)
        count += 1
    return RiskContext(
        duplicate_count=count,
        fingerprint=digest.hexdigest(),
        captured_at=captured_at,
        complete=True,
    )
