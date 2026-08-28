"""student grade-group snapshot relationship

Revision ID: 8a2c1d7e4b90
Revises: 8a1e7c4d92bf
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a2c1d7e4b90"
down_revision: Union[str, Sequence[str], None] = "8a1e7c4d92bf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studentgrademembership",
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("grade_id", sa.Integer(), nullable=False),
        sa.Column("grade_unit_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("cohort_label", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["student.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["grade_id"], ["grade.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["grade_unit_id"], ["organizationunit.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "student_id", "academic_year", name="uq_studentgrademembership_student_year"),
    )
    op.create_index("ix_studentgrademembership_tenant_id", "studentgrademembership", ["tenant_id"])
    op.create_index("ix_studentgrademembership_student_id", "studentgrademembership", ["student_id"])
    op.create_index("ix_studentgrademembership_grade_id", "studentgrademembership", ["grade_id"])
    op.create_index("ix_studentgrademembership_grade_unit_id", "studentgrademembership", ["grade_unit_id"])
    op.create_index("ix_studentgrademembership_academic_year", "studentgrademembership", ["academic_year"])
    op.create_index("ix_studentgrademembership_cohort_label", "studentgrademembership", ["cohort_label"])
    op.create_index("ix_studentgrademembership_status", "studentgrademembership", ["status"])


def downgrade() -> None:
    for name in (
        "ix_studentgrademembership_status",
        "ix_studentgrademembership_cohort_label",
        "ix_studentgrademembership_academic_year",
        "ix_studentgrademembership_grade_unit_id",
        "ix_studentgrademembership_grade_id",
        "ix_studentgrademembership_student_id",
        "ix_studentgrademembership_tenant_id",
    ):
        op.drop_index(name, table_name="studentgrademembership")
    op.drop_table("studentgrademembership")
