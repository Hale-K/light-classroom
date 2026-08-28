"""campus capacity, grade campus and administrative class home room planning

Revision ID: f6b9c82a10d4
Revises: e5ac9812d620
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6b9c82a10d4"
down_revision: Union[str, Sequence[str], None] = "e5ac9812d620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campus", sa.Column("student_capacity", sa.Integer(), nullable=True))
    op.add_column("grade", sa.Column("campus_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_grade_campus_id"), "grade", ["campus_id"], unique=False)
    op.add_column("class", sa.Column("campus_id", sa.Integer(), nullable=True))
    op.add_column("class", sa.Column("home_room_id", sa.Integer(), nullable=True))
    op.add_column("class", sa.Column("planned_student_count", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_class_campus_id"), "class", ["campus_id"], unique=False)
    op.create_index(op.f("ix_class_home_room_id"), "class", ["home_room_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_class_home_room_id"), table_name="class")
    op.drop_index(op.f("ix_class_campus_id"), table_name="class")
    op.drop_column("class", "planned_student_count")
    op.drop_column("class", "home_room_id")
    op.drop_column("class", "campus_id")
    op.drop_index(op.f("ix_grade_campus_id"), table_name="grade")
    op.drop_column("grade", "campus_id")
    op.drop_column("campus", "student_capacity")
