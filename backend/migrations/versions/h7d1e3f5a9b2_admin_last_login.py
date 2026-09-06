"""add last_login_at to platform_admin

Revision ID: h7d1e3f5a9b2
Revises: g4b6c8e0f1a3
"""
from alembic import op
import sqlalchemy as sa

revision = "h7d1e3f5a9b2"
down_revision = "g4b6c8e0f1a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platformadmin", sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("platformadmin", "last_login_at")
