"""Ensure extraction results belong to their processing job's document.

Revision ID: 7e520590a521
Revises: 46921fac6739
"""

from alembic import op

revision = "7e520590a521"
down_revision = "46921fac6739"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_job_document", "processing_jobs", ["job_id", "document_id"])
    op.create_foreign_key(
        "fk_result_job_document",
        "extraction_results",
        "processing_jobs",
        ["job_id", "document_id"],
        ["job_id", "document_id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint("fk_result_job_document", "extraction_results", type_="foreignkey")
    op.drop_constraint("uq_job_document", "processing_jobs", type_="unique")
