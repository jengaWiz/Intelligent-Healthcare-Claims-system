import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "current_state IN ('RECEIVED','PROCESSING','READY','REVIEW_REQUIRED','FAILED','REJECTED')",
            name="ck_claim_state",
        ),
        CheckConstraint("version >= 1", name="ck_claim_version"),
    )
    claim_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    current_state = Column(String(50), nullable=False, default="RECEIVED")
    version = Column(Integer, nullable=False, default=1)
    source_system = Column(String(100))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    documents = relationship(
        "Document", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True
    )
    reviews = relationship(
        "Review", back_populates="claim", cascade="all, delete-orphan", passive_deletes=True
    )
