import uuid
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    extraction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False
    )

    extracted_data = Column(JSON, nullable=False)
    confidence = Column(Float, nullable=False)
    reasoning = Column(String, nullable=True)
    confidence_scores = Column(JSON, nullable=True)

    extraction_engine = Column(String(100), nullable=False)
    extraction_version = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="extraction_result")