"""exam room catalog

Revision ID: c38ea617f409
Revises: b27d9a51c308
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c38ea617f409"
down_revision: Union[str, Sequence[str], None] = "b27d9a51c308"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "examroom",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("building", sa.String(length=100), nullable=True),
        sa.Column("room_type", sa.String(length=20), nullable=False),
        sa.Column("source_class_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_examroom_tenant_name"),
        comment="学校考场资源",
        if_not_exists=True,
    )
    for column in ["tenant_id", "is_deleted", "source_class_id"]:
        op.create_index(op.f(f"ix_examroom_{column}"), "examroom", [column], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_table("examroom", if_exists=True)
