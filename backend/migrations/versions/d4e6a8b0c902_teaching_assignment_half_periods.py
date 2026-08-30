"""allow half-period teaching assignments

Revision ID: d4e6a8b0c902
Revises: b8d3f2a6c901
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "d4e6a8b0c902"
down_revision = "b8d3f2a6c901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "teachingassignment", "weekly_periods",
        existing_type=sa.Integer(), type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="weekly_periods::double precision",
    )


def downgrade() -> None:
    op.alter_column(
        "teachingassignment", "weekly_periods",
        existing_type=sa.Float(), type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="floor(weekly_periods)::integer",
    )
