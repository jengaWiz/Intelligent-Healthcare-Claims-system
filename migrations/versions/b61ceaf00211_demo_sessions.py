"""Add isolated reviewer workspaces and revocable browser sessions."""

import sqlalchemy as sa
from alembic import op

revision = "b61ceaf00211"
down_revision = "a04b9c2d310f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "claims", sa.Column("owner_id", sa.String(100), nullable=False, server_default="api")
    )
    op.create_index("ix_claims_owner_id", "claims", ["owner_id"])
    op.create_table(
        "browser_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"])


def downgrade():
    op.drop_table("browser_sessions")
    op.drop_index("ix_claims_owner_id", "claims")
    op.drop_column("claims", "owner_id")
