"""组织实体租户内唯一性约束

Revision ID: 3d8f1a2b6c4d
Revises: 2c7d8e9f0a1b
Create Date: 2026-08-26

- 年级: 同一租户内名称唯一 (uq_grade_tenant_name)
- 班级: 同一租户同一年级内名称唯一 (uq_class_grade_name)
- 建筑: 模型已声明但从未迁移到库 (uq_building_campus_name)
- 学生: 同一租户内学号唯一 (uq_student_tenant_no)
- 现有名称先做规范化（去除空白字符），避免仅差空格的重复行绕过唯一约束
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "3d8f1a2b6c4d"
down_revision: Union[str, Sequence[str], None] = "2c7d8e9f0a1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(table: str) -> None:
    op.execute(f"UPDATE {table} SET name = regexp_replace(name, '\\s', '', 'g') WHERE name ~ '\\s'")


def _create_uq(table: str, name: str, cols: list[str]) -> None:
    bind = op.get_bind()
    exists = bind.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
        {"n": name},
    ).scalar()
    if not exists:
        op.create_unique_constraint(name, table, cols)


def upgrade() -> None:
    _normalize("grade")
    _normalize("class")
    _normalize("building")
    _create_uq("grade", "uq_grade_tenant_name", ["tenant_id", "name"])
    _create_uq("class", "uq_class_grade_name", ["tenant_id", "grade_id", "name"])
    _create_uq("building", "uq_building_campus_name", ["tenant_id", "campus_id", "name"])
    _create_uq("student", "uq_student_tenant_no", ["tenant_id", "student_no"])


def downgrade() -> None:
    op.drop_constraint("uq_student_tenant_no", "student", type_="unique")
    op.drop_constraint("uq_building_campus_name", "building", type_="unique")
    op.drop_constraint("uq_class_grade_name", "class", type_="unique")
    op.drop_constraint("uq_grade_tenant_name", "grade", type_="unique")
