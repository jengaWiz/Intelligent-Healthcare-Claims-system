from models.claim import Claim
from sqlalchemy.orm.session import Session

"""
creates a claim and adds it to the database. Defines the only allowed states for a claim object. 
"""
ALLOWED_STATES = {
    "RECEIVED",
    "VALIDATED",
    "EXTRACTION_PENDING",
    "EXTRACTED",
    "RISK_CLASSIFIED"
}

def create_claim(db: Session, source_system: str | None = None) -> Claim:  
    claim = Claim(
        current_state="RECEIVED",
        source_system=source_system
    )

    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim

