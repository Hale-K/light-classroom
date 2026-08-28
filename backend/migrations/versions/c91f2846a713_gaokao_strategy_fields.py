"""add strategy-neutral gaokao choice fields

Revision ID: c91f2846a713
Revises: b27a6e18c502
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c91f2846a713"
down_revision: Union[str, Sequence[str], None] = "b27a6e18c502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("gaokaoscheme", sa.Column("strategy_config", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("studentsubjectchoice", sa.Column("selected_subject_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("studentsubjectchoice", sa.Column("stream", sa.String(length=20), nullable=True))
    op.alter_column("studentsubjectchoice", "primary_subject_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "UPDATE studentsubjectchoice "
        "SET selected_subject_ids = (jsonb_build_array(primary_subject_id) || secondary_subject_ids::jsonb)::json "
        "WHERE primary_subject_id IS NOT NULL AND selected_subject_ids::jsonb = '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE studentsubjectchoice SET primary_subject_id = 0 "
        "WHERE primary_subject_id IS NULL"
    )
    op.alter_column("studentsubjectchoice", "primary_subject_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("studentsubjectchoice", "stream")
    op.drop_column("studentsubjectchoice", "selected_subject_ids")
    op.drop_column("gaokaoscheme", "strategy_config")
