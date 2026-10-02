"""Retain all accepted idempotency keys, including duplicate active requests."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a04b9c2d310f"
down_revision = "7e520590a521"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_requests",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id", "document_id"],
            ["processing_jobs.job_id", "processing_jobs.document_id"],
            name="fk_request_job_document",
            ondelete="CASCADE",
        ),
    )
    op.execute(
        "INSERT INTO job_requests (key, job_id, document_id) "
        "SELECT idempotency_key, job_id, document_id FROM processing_jobs "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade():
    op.drop_table("job_requests")
