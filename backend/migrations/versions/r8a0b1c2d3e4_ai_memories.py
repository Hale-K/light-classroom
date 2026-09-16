"""Add structured assistant memories."""
from alembic import op
import sqlalchemy as sa

revision = "r8a0b1c2d3e4"
down_revision = "q7f9a2c4e6b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False),
        sa.Column("predicate", sa.String(64), nullable=False),
        sa.Column("value", sa.String(1000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_message", sa.String(4000)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_memory_tenant_id", "ai_memory", ["tenant_id"])
    op.create_index("ix_ai_memory_user_id", "ai_memory", ["user_id"])
    op.create_index("ix_ai_memory_type", "ai_memory", ["type"])
    op.create_index("ix_ai_memory_status", "ai_memory", ["status"])


def downgrade():
    op.drop_table("ai_memory")
