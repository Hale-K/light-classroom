"""Resumable assistant request status. Revision c0e3f4a5b6d7."""
from alembic import context, op
import sqlalchemy as sa

revision = "c0e3f4a5b6d7"
down_revision = "b9d2e3f4a5c6"
branch_labels = None
depends_on = None


def upgrade():
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("ai_run"):
        return
    op.create_table("ai_run",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("phase_started_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ai_run_tenant_id", "ai_run", ["tenant_id"])
    op.create_index("ix_ai_run_user_id", "ai_run", ["user_id"])


def downgrade():
    op.drop_table("ai_run")
