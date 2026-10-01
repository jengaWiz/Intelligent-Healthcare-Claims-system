import uuid

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "document_state IN ('UPLOADED','QUEUED','PROCESSING','EXTRACTED','FAILED')",
            name="ck_document_state",
        ),
        CheckConstraint("byte_size > 0", name="ck_document_size"),
    )
    document_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("claims.claim_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    file_name = Column(String(225), nullable=False)
    file_mime_type = Column(String(100), nullable=False)
    byte_size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    storage_path = Column(String(500), nullable=False)
    document_state = Column(String(50), nullable=False, default="UPLOADED")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    claim = relationship("Claim", back_populates="documents")
    jobs = relationship(
        "ProcessingJob",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    extraction_result = relationship(
        "ExtractionResult",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
