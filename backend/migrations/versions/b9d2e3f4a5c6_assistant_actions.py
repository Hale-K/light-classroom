"""Persist teacher-confirmed assistant drafts.

Revision ID: b9d2e3f4a5c6
Revises: a8c1d2e3f4b5
"""
from alembic import context, op
import sqlalchemy as sa

revision = "b9d2e3f4a5c6"
down_revision = "a8c1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade():
    # Development init_db may already have created the SQLModel table.
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("ai_action"):
        return
    op.create_table(
        "ai_action",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_action_tenant_id", "ai_action", ["tenant_id"])
    op.create_index("ix_ai_action_user_id", "ai_action", ["user_id"])


def downgrade():
    op.drop_table("ai_action")
