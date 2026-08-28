"""rule-based room allocation to grade cohorts

Revision ID: 2d6a8f04b731
Revises: 1c4f93a8d2e7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d6a8f04b731"
down_revision: Union[str, Sequence[str], None] = "1c4f93a8d2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resourceallocationrule",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("cohort_label", sa.String(length=30), nullable=False),
        sa.Column("campus_id", sa.Integer(), nullable=False),
        sa.Column("building_id", sa.Integer(), nullable=True),
        sa.Column("floor_from", sa.Integer(), nullable=True),
        sa.Column("floor_to", sa.Integer(), nullable=True),
        sa.Column("room_type", sa.String(length=30), nullable=True),
        sa.Column("min_capacity", sa.Integer(), nullable=True),
        sa.Column("required_feature", sa.String(length=50), nullable=True),
        sa.Column("allocation_mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "tenant_id", "cohort_label", "campus_id", "building_id", "room_type",
        "allocation_mode", "status", "created_by",
    ):
        op.create_index(op.f(f"ix_resourceallocationrule_{column}"), "resourceallocationrule", [column], unique=False)

    op.create_table(
        "roomcohortallocation",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("cohort_label", sa.String(length=30), nullable=False),
        sa.Column("allocation_mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "rule_id", "room_id", name="uq_roomcohortallocation_rule_room"),
    )
    for column in ("tenant_id", "rule_id", "room_id", "cohort_label", "allocation_mode", "status"):
        op.create_index(op.f(f"ix_roomcohortallocation_{column}"), "roomcohortallocation", [column], unique=False)


def downgrade() -> None:
    for column in reversed(("tenant_id", "rule_id", "room_id", "cohort_label", "allocation_mode", "status")):
        op.drop_index(op.f(f"ix_roomcohortallocation_{column}"), table_name="roomcohortallocation")
    op.drop_table("roomcohortallocation")
    for column in reversed((
        "tenant_id", "cohort_label", "campus_id", "building_id", "room_type",
        "allocation_mode", "status", "created_by",
    )):
        op.drop_index(op.f(f"ix_resourceallocationrule_{column}"), table_name="resourceallocationrule")
    op.drop_table("resourceallocationrule")
