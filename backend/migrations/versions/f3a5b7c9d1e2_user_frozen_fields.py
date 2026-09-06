"""add frozen / freeze_reason to user

Revision ID: f3a5b7c9d1e2
Revises: e2f4a6b8c0d1
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a5b7c9d1e2"
down_revision = "e2f4a6b8c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("user", sa.Column("freeze_reason", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "freeze_reason")
    op.drop_column("user", "frozen")
