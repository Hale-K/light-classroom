"""add last_login_at to user

Revision ID: g4b6c8e0f1a3
Revises: f3a5b7c9d1e2
"""
from alembic import op
import sqlalchemy as sa

revision = "g4b6c8e0f1a3"
down_revision = "f3a5b7c9d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "last_login_at")
