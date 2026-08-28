"""new gaokao walk classes

Revision ID: b27a6e18c502
Revises: 4c81e630a4fb
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b27a6e18c502"
down_revision: Union[str, Sequence[str], None] = "4c81e630a4fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gaokaoscheme",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("province", sa.String(length=50), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("entry_year", sa.Integer(), nullable=False),
        sa.Column("required_subject_ids", sa.JSON(), nullable=False),
        sa.Column("primary_subject_ids", sa.JSON(), nullable=False),
        sa.Column("secondary_subject_ids", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "entry_year", name="uq_gaokaoscheme_tenant_entry_year"),
        comment="新高考方案",
    )
    op.create_table(
        "studentsubjectchoice",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("scheme_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("effective_term", sa.String(length=20), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("primary_subject_id", sa.Integer(), nullable=False),
        sa.Column("secondary_subject_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "student_id", "academic_year", "effective_term", name="uq_studentchoice_student_term"),
        comment="学生新高考选科",
    )
    op.create_table(
        "teachingclass",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("term", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("weekly_periods", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("room", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "grade_id", "subject_id", "academic_year", "term", "sequence", name="uq_teachingclass_subject_sequence"),
        comment="新高考走班教学班",
    )
    op.create_table(
        "teachingclassstudent",
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teaching_class_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teaching_class_id", "student_id", name="uq_teachingclassstudent_member"),
        comment="教学班学生成员",
    )
    op.create_table(
        "teachingclassschedule",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("teaching_class_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("term", sa.String(length=20), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("room", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teaching_class_id", "weekday", "period", name="uq_teachingclassschedule_slot"),
        comment="走班教学班课表",
    )
    for table, columns in {
        "gaokaoscheme": ["tenant_id", "entry_year", "is_active"],
        "studentsubjectchoice": ["tenant_id", "student_id", "scheme_id", "academic_year", "primary_subject_id", "status"],
        "teachingclass": ["tenant_id", "grade_id", "subject_id", "academic_year", "teacher_id", "status"],
        "teachingclassstudent": ["tenant_id", "teaching_class_id", "student_id"],
        "teachingclassschedule": ["tenant_id", "teaching_class_id", "teacher_id", "subject_id", "academic_year", "weekday", "period"],
    }.items():
        for column in columns:
            op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)


def downgrade() -> None:
    op.drop_table("teachingclassschedule")
    op.drop_table("teachingclassstudent")
    op.drop_table("teachingclass")
    op.drop_table("studentsubjectchoice")
    op.drop_table("gaokaoscheme")
