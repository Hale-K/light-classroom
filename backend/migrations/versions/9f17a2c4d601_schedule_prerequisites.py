"""schedule prerequisites

Revision ID: 9f17a2c4d601
Revises: 6da9d303d39b
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f17a2c4d601"
down_revision: Union[str, Sequence[str], None] = "6da9d303d39b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teachingassignment", sa.Column("term", sa.String(length=20), nullable=False, server_default="1"))
    op.add_column("teachingassignment", sa.Column("weekly_periods", sa.Integer(), nullable=False, server_default="4"))
    op.add_column("teachingassignment", sa.Column("room", sa.String(length=50), nullable=True))
    op.execute("ALTER TYPE seatrule ADD VALUE IF NOT EXISTS 'roster'")
    op.execute("ALTER TYPE seatrule ADD VALUE IF NOT EXISTS 'random'")
    for name in ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]:
        op.execute(sa.text("INSERT INTO subject (name) VALUES (:name) ON CONFLICT (name) DO NOTHING").bindparams(name=name))


def downgrade() -> None:
    op.drop_column("teachingassignment", "room")
    op.drop_column("teachingassignment", "weekly_periods")
    op.drop_column("teachingassignment", "term")
