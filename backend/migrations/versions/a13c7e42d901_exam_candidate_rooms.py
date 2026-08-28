"""exam candidate rooms

Revision ID: a13c7e42d901
Revises: f4c9217d6a10
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a13c7e42d901"
down_revision: Union[str, Sequence[str], None] = "f4c9217d6a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "examroomassignment",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("exam_schedule_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("session_index", sa.Integer(), nullable=False),
        sa.Column("room_name", sa.String(length=100), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("invigilator_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_schedule_id", "room_name", name="uq_examroom_schedule_room"),
        comment="考试考场安排",
        if_not_exists=True,
    )
    for column in ["tenant_id", "exam_id", "exam_schedule_id", "paper_id", "grade_id", "subject_id", "exam_date", "session_index"]:
        op.create_index(op.f(f"ix_examroomassignment_{column}"), "examroomassignment", [column], unique=False, if_not_exists=True)

    op.create_table(
        "examcandidateassignment",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_id", sa.Integer(), nullable=False),
        sa.Column("exam_schedule_id", sa.Integer(), nullable=False),
        sa.Column("exam_room_assignment_id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("exam_date", sa.Date(), nullable=False),
        sa.Column("session_index", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("room_name", sa.String(length=100), nullable=False),
        sa.Column("seat_no", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_id", "paper_id", "student_id", name="uq_examcandidate_paper_student"),
        comment="考试考生座位安排",
        if_not_exists=True,
    )
    for column in ["tenant_id", "exam_id", "exam_schedule_id", "exam_room_assignment_id", "paper_id", "grade_id", "subject_id", "student_id", "exam_date", "session_index"]:
        op.create_index(op.f(f"ix_examcandidateassignment_{column}"), "examcandidateassignment", [column], unique=False, if_not_exists=True)


def downgrade() -> None:
    op.drop_table("examcandidateassignment", if_exists=True)
    op.drop_table("examroomassignment", if_exists=True)
