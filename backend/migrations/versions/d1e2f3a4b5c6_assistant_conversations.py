"""Persist the active assistant conversation.

Revision ID: d1e2f3a4b5c6
Revises: c0e3f4a5b6d7
"""
from alembic import context, op
import sqlalchemy as sa

revision = "d1e2f3a4b5c6"
down_revision = "c0e3f4a5b6d7"
branch_labels = None
depends_on = None


def upgrade():
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("ai_conversation"):
        return
    op.create_table(
        "ai_conversation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(8000), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_ai_conversation_tenant_user"),
    )
    op.create_index("ix_ai_conversation_tenant_id", "ai_conversation", ["tenant_id"])
    op.create_index("ix_ai_conversation_user_id", "ai_conversation", ["user_id"])


def downgrade():
    op.drop_table("ai_conversation")
