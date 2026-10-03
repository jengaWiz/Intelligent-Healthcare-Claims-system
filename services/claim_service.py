"""Services flush changes; callers own the transaction and commit/rollback."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import APIError
from models import Claim
from services.access_service import scoped


def get_claim(db, claim_id, *, lock=False):
    query = scoped(select(Claim).where(Claim.claim_id == claim_id), db)
    if lock:
        # Refresh an already-loaded identity after waiting for another transaction.
        query = query.with_for_update().execution_options(populate_existing=True)
    claim = db.scalar(query)
    if claim is None:
        raise APIError(404, "claim_not_found", "Claim not found")
    return claim


def create_claim(db: Session, source_system: str | None = None) -> Claim:
    claim = Claim(
        current_state="RECEIVED",
        source_system=source_system,
        owner_id=db.info.get("actor_id", "api"),
    )
    db.add(claim)
    db.flush()
    return claim
