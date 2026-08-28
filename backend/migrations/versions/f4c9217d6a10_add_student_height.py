"""add student height

Revision ID: f4c9217d6a10
Revises: e48b2a7f3310
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c9217d6a10"
down_revision: Union[str, Sequence[str], None] = "e48b2a7f3310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("student", sa.Column("height_cm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("student", "height_cm")
