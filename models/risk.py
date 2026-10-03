"""Immutable assessments and independent human acknowledgments."""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from database.base import Base


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "document_id"],
            ["documents.claim_id", "documents.document_id"],
            name="fk_risk_claim_document",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["extraction_id", "document_id"],
            ["extraction_results.extraction_id", "extraction_results.document_id"],
            name="fk_risk_extraction_document",
            ondelete="CASCADE",
        ),
        UniqueConstraint("claim_id", "revision", name="uq_risk_claim_revision"),
        CheckConstraint("claim_version >= 1 AND revision >= 1", name="ck_risk_versions"),
        CheckConstraint(
            "level IN ('LOW','MEDIUM','HIGH','INSUFFICIENT_DATA')", name="ck_risk_level"
        ),
        CheckConstraint(
            "length(input_fingerprint) = 64 AND length(context_fingerprint) = 64",
            name="ck_risk_fingerprints",
        ),
        Index("ix_risk_level", "level"),
    )
    assessment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), nullable=False)
    document_id = Column(UUID(as_uuid=True), nullable=False)
    extraction_id = Column(UUID(as_uuid=True), nullable=False)
    claim_version = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    level = Column(String(30), nullable=False)
    policy_version = Column(String(50), nullable=False)
    signals = Column(JSON, nullable=False)
    input_fingerprint = Column(String(64), nullable=False)
    context_fingerprint = Column(String(64), nullable=False)
    assessed_at = Column(DateTime(timezone=True), nullable=False)
    context_at = Column(DateTime(timezone=True), nullable=False)


class RiskAcknowledgment(Base):
    __tablename__ = "risk_acknowledgments"
    __table_args__ = (
        UniqueConstraint("assessment_id", "actor_id", name="uq_risk_ack_actor"),
        CheckConstraint("length(trim(reason)) >= 1", name="ck_risk_ack_reason"),
    )
    acknowledgment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("risk_assessments.assessment_id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_id = Column(String(100), nullable=False)
    reason = Column(String(2000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
