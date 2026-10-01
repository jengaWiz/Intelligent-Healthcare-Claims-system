"""Services flush changes; callers own the transaction and commit/rollback."""

from sqlalchemy.orm import Session

from models import Claim


def create_claim(db: Session, source_system: str | None = None) -> Claim:
    claim = Claim(current_state="RECEIVED", source_system=source_system)
    db.add(claim)
    db.flush()
    return claim
