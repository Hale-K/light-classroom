"""add school gaokao defaults

Revision ID: d36e71f9a204
Revises: c91f2846a713
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d36e71f9a204"
down_revision: Union[str, Sequence[str], None] = "c91f2846a713"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("province", sa.String(length=50), nullable=False, server_default="全国通用"),
    )
    op.add_column(
        "tenant",
        sa.Column("gaokao_mode", sa.String(length=20), nullable=False, server_default="3+1+2"),
    )


def downgrade() -> None:
    op.drop_column("tenant", "gaokao_mode")
    op.drop_column("tenant", "province")
