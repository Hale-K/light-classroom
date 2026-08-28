"""add teacher level to staff accounts

Revision ID: a7c4e9d1b2f0
Revises: 9b3e7a1c2d44
"""
from alembic import op
import sqlalchemy as sa

revision = "a7c4e9d1b2f0"
down_revision = "9b3e7a1c2d44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("teacher_level", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "teacher_level")
