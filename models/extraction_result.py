import uuid

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class ExtractionResult(Base):
    __tablename__ = "extraction_results"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_result_confidence"),
        CheckConstraint("outcome IN ('READY','REVIEW_REQUIRED')", name="ck_result_outcome"),
    )
    extraction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    extracted_data = Column(JSON, nullable=False)
    normalized_data = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(String)
    outcome = Column(String(30), nullable=False)
    extraction_engine = Column(String(100), nullable=False)
    extraction_version = Column(String(50), nullable=False)
    provenance = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    document = relationship("Document", back_populates="extraction_result")
    validation = relationship(
        "ValidationOutcome",
        back_populates="extraction_result",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
