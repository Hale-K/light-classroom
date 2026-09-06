"""Persist resumable scheduling generation jobs.

Revision ID: e2f4a6b8c0d1
Revises: d1e2f3a4b5c6
"""
from alembic import context, op
import sqlalchemy as sa

revision = "e2f4a6b8c0d1"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    if not context.is_offline_mode() and sa.inspect(op.get_bind()).has_table("scheduling_generate_job"):
        return
    op.create_table(
        "scheduling_generate_job",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("term", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_scheduling_generate_job_tenant_id", "scheduling_generate_job", ["tenant_id"])
    op.create_index("ix_scheduling_generate_job_academic_year", "scheduling_generate_job", ["academic_year"])
    op.create_index("ix_scheduling_generate_job_term", "scheduling_generate_job", ["term"])
    op.create_index("ix_scheduling_generate_job_status", "scheduling_generate_job", ["status"])
    op.create_index(
        "ix_scheduling_generate_job_scope_status",
        "scheduling_generate_job",
        ["tenant_id", "academic_year", "term", "status"],
    )


def downgrade():
    op.drop_table("scheduling_generate_job")
