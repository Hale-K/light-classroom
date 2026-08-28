"""exam scope, room state and invigilator availability

Revision ID: e5ac9812d620
Revises: d49fb728a510
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5ac9812d620"
down_revision: Union[str, Sequence[str], None] = "d49fb728a510"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("examroom", sa.Column("status", sa.String(length=20), nullable=False, server_default="available"))
    op.create_index(op.f("ix_examroom_status"), "examroom", ["status"], unique=False)
    op.create_table(
        "examschedulingconfig",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("grade_ids", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("excluded_dates", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("sessions", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("invigilators_per_room", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "exam_id", name="uq_examschedulingconfig_exam"),
    )
    op.create_index(op.f("ix_examschedulingconfig_exam_id"), "examschedulingconfig", ["exam_id"], unique=False)
    op.create_index(op.f("ix_examschedulingconfig_tenant_id"), "examschedulingconfig", ["tenant_id"], unique=False)
    op.create_table(
        "examinvigilatoravailability",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("leave_start", sa.Date(), nullable=True),
        sa.Column("leave_end", sa.Date(), nullable=True),
        sa.Column("unavailable_slots", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "exam_id", "teacher_id", name="uq_examinvigilator_exam_teacher"),
    )
    op.create_index(op.f("ix_examinvigilatoravailability_exam_id"), "examinvigilatoravailability", ["exam_id"], unique=False)
    op.create_index(op.f("ix_examinvigilatoravailability_teacher_id"), "examinvigilatoravailability", ["teacher_id"], unique=False)
    op.create_index(op.f("ix_examinvigilatoravailability_tenant_id"), "examinvigilatoravailability", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_table("examinvigilatoravailability")
    op.drop_table("examschedulingconfig")
    op.drop_index(op.f("ix_examroom_status"), table_name="examroom")
    op.drop_column("examroom", "status")
