"""Every accepted idempotency key stays bound to its original document/job."""

from sqlalchemy import Column, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID

from database.base import Base


class JobRequest(Base):
    __tablename__ = "job_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "document_id"],
            ["processing_jobs.job_id", "processing_jobs.document_id"],
            name="fk_request_job_document",
            ondelete="CASCADE",
        ),
    )
    key = Column(String(128), primary_key=True)
    job_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(UUID(as_uuid=True), nullable=False)
