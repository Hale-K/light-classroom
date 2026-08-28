"""exam scheduling

Revision ID: 4c81e630a4fb
Revises: 9f17a2c4d601
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c81e630a4fb"
down_revision: Union[str, Sequence[str], None] = "9f17a2c4d601"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "examschedule",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("session_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("room", sa.String(length=100), nullable=False),
        sa.Column("invigilator_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="考试日程",
    )
    for column in ["tenant_id", "exam_id", "paper_id", "grade_id", "subject_id", "exam_date", "invigilator_id"]:
        op.create_index(op.f(f"ix_examschedule_{column}"), "examschedule", [column], unique=False)


def downgrade() -> None:
    op.drop_table("examschedule")
