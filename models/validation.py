import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class ValidationOutcome(Base):
    __tablename__ = "validation_outcomes"
    __table_args__ = (
        CheckConstraint(
            "validation_score >= 0 AND validation_score <= 1", name="ck_validation_score"
        ),
        CheckConstraint(
            "semantic_status IN ('completed','unavailable')", name="ck_semantic_status"
        ),
    )
    validation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_id = Column(
        UUID(as_uuid=True),
        ForeignKey("extraction_results.extraction_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    is_valid = Column(Boolean, nullable=False)
    validation_score = Column(Float, nullable=False)
    semantic_status = Column(String(20), nullable=False)
    issues = Column(JSON, nullable=False, default=list)
    recommendations = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    extraction_result = relationship("ExtractionResult", back_populates="validation")
