import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('approve','correct','reject')", name="ck_review_decision"),
        CheckConstraint(
            "previous_version >= 1 AND new_version = previous_version + 1", name="ck_review_version"
        ),
        UniqueConstraint("claim_id", "new_version", name="uq_review_claim_version"),
    )
    review_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(
        UUID(as_uuid=True), ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False
    )
    actor_id = Column(String(100), nullable=False)
    decision = Column(String(20), nullable=False)
    reason = Column(String(2000), nullable=False)
    previous_version = Column(Integer, nullable=False)
    new_version = Column(Integer, nullable=False)
    before_data = Column(JSON, nullable=False)
    after_data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    claim = relationship("Claim", back_populates="reviews")
