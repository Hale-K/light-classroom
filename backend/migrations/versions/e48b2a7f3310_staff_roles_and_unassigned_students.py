"""staff roles and unassigned students

Revision ID: e48b2a7f3310
Revises: d36e71f9a204
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e48b2a7f3310"
down_revision: Union[str, Sequence[str], None] = "d36e71f9a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("student", "class_id", existing_type=sa.Integer(), nullable=True)
    roles = (
        ("head_teacher", "班主任", "负责行政班学生管理与班级排座"),
        ("subject_teacher", "任教老师", "承担学科教学、建卷与阅卷任务"),
        ("academic_director", "教导主任", "负责选科分班、排课与排考等教学管理"),
    )
    for code, name, description in roles:
        op.execute(sa.text(
            "INSERT INTO role (code, name, description) VALUES (:code, :name, :description) "
            "ON CONFLICT (code) DO NOTHING"
        ).bindparams(code=code, name=name, description=description))


def downgrade() -> None:
    op.execute("DELETE FROM userrole WHERE role_id IN (SELECT id FROM role WHERE code IN ('head_teacher', 'subject_teacher', 'academic_director'))")
    op.execute("DELETE FROM role WHERE code IN ('head_teacher', 'subject_teacher', 'academic_director')")
    op.alter_column("student", "class_id", existing_type=sa.Integer(), nullable=False)
