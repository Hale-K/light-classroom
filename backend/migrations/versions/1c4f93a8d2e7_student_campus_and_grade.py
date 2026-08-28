"""student campus and grade before administrative class assignment

Revision ID: 1c4f93a8d2e7
Revises: f6b9c82a10d4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1c4f93a8d2e7"
down_revision: Union[str, Sequence[str], None] = "f6b9c82a10d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("student", sa.Column("campus_id", sa.Integer(), nullable=True))
    op.add_column("student", sa.Column("grade_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_student_campus_id"), "student", ["campus_id"], unique=False)
    op.create_index(op.f("ix_student_grade_id"), "student", ["grade_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_student_grade_id"), table_name="student")
    op.drop_index(op.f("ix_student_campus_id"), table_name="student")
    op.drop_column("student", "grade_id")
    op.drop_column("student", "campus_id")
