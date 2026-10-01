import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database.base import Base


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint("job_id", "document_id", name="uq_job_document"),
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','RETRY_WAIT','SUCCEEDED','FAILED')", name="ck_job_state"
        ),
        CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts AND max_attempts >= 1",
            name="ck_job_attempts",
        ),
        CheckConstraint(
            "state != 'RUNNING' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_job_running_lease",
        ),
        Index(
            "uq_active_document_job",
            "document_id",
            unique=True,
            postgresql_where=text("state IN ('QUEUED','RUNNING','RETRY_WAIT')"),
        ),
        Index("ix_job_poll", "state", "next_attempt_at"),
    )
    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False
    )
    state = Column(String(20), nullable=False, default="QUEUED")
    idempotency_key = Column(String(128), unique=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    lease_owner = Column(UUID(as_uuid=True))
    lease_expires_at = Column(DateTime(timezone=True))
    next_attempt_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_code = Column(String(100))
    error_message = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    document = relationship("Document", back_populates="jobs")
