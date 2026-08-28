"""exam venues

Revision ID: b27d9a51c308
Revises: a13c7e42d901
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b27d9a51c308"
down_revision: Union[str, Sequence[str], None] = "a13c7e42d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "examvenue",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_class_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "exam_id", "name", name="uq_examvenue_exam_name"),
        comment="考试考场配置",
        if_not_exists=True,
    )
    for column in ["tenant_id", "exam_id", "source_class_id"]:
        op.create_index(op.f(f"ix_examvenue_{column}"), "examvenue", [column], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_table("examvenue", if_exists=True)
