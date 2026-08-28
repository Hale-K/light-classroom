"""protect teaching assignments and schedules with foreign keys

Revision ID: 8a1e7c4d92bf
Revises: 5f2a8c4e7b1d
"""
from typing import Sequence, Union

from alembic import op


revision: str = "8a1e7c4d92bf"
down_revision: Union[str, Sequence[str], None] = "5f2a8c4e7b1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_teachingassignment_teacher",
        "teachingassignment",
        "user",
        ["teacher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_teachingassignment_subject",
        "teachingassignment",
        "subject",
        ["subject_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_teachingassignment_class",
        "teachingassignment",
        "class",
        ["class_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_schedule_class",
        "schedule",
        "class",
        ["class_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_schedule_subject",
        "schedule",
        "subject",
        ["subject_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_schedule_teacher",
        "schedule",
        "user",
        ["teacher_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_schedule_teacher", "schedule", type_="foreignkey")
    op.drop_constraint("fk_schedule_subject", "schedule", type_="foreignkey")
    op.drop_constraint("fk_schedule_class", "schedule", type_="foreignkey")
    op.drop_constraint("fk_teachingassignment_class", "teachingassignment", type_="foreignkey")
    op.drop_constraint("fk_teachingassignment_subject", "teachingassignment", type_="foreignkey")
    op.drop_constraint("fk_teachingassignment_teacher", "teachingassignment", type_="foreignkey")
