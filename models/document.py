import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base

class Document(Base):
    _tablename_ = "documents"

    documents_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    claim_id = Column(
        UUID(ac_uuid=True),
        ForeignKey("claims.claim_id", ondelete="CASCADE"),
        nullable=False
    )
    
    document_type = Column(String(50), nullable=True)
    file_name = Column(String(225), nullable=False)
    file_mime_type = Column(String(100), nullable=False)

    storage_path = Column(String(500), nullable=False)

    document_state = Column(String(50), nullable=False, default="UPLOADED")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    extraction_result = relationship(
    "ExtractionResult",
    back_populates="document",
    uselist=False
)
