"""scope resource allocations by academic year and term

Revision ID: 1a2b3c4d5e6f
Revises: f6b9c82a10d4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = ("f6b9c82a10d4", "5b8e3d7f1c20")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resourceallocationrule", sa.Column("academic_year", sa.String(length=20), nullable=False, server_default="2026-2027"))
    op.add_column("resourceallocationrule", sa.Column("term", sa.String(length=20), nullable=False, server_default="1"))
    op.create_index(op.f("ix_resourceallocationrule_academic_year"), "resourceallocationrule", ["academic_year"], unique=False)
    op.create_index(op.f("ix_resourceallocationrule_term"), "resourceallocationrule", ["term"], unique=False)
    op.add_column("roomcohortallocation", sa.Column("academic_year", sa.String(length=20), nullable=False, server_default="2026-2027"))
    op.add_column("roomcohortallocation", sa.Column("term", sa.String(length=20), nullable=False, server_default="1"))
    op.create_index(op.f("ix_roomcohortallocation_academic_year"), "roomcohortallocation", ["academic_year"], unique=False)
    op.create_index(op.f("ix_roomcohortallocation_term"), "roomcohortallocation", ["term"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_roomcohortallocation_term"), table_name="roomcohortallocation")
    op.drop_index(op.f("ix_roomcohortallocation_academic_year"), table_name="roomcohortallocation")
    op.drop_column("roomcohortallocation", "term")
    op.drop_column("roomcohortallocation", "academic_year")
    op.drop_index(op.f("ix_resourceallocationrule_term"), table_name="resourceallocationrule")
    op.drop_index(op.f("ix_resourceallocationrule_academic_year"), table_name="resourceallocationrule")
    op.drop_column("resourceallocationrule", "term")
    op.drop_column("resourceallocationrule", "academic_year")
