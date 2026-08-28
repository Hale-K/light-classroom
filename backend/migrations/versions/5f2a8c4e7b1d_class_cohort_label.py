"""班级增加届(cohort_label)维度

Revision ID: 5f2a8c4e7b1d
Revises: 4e9c2b7d1f5a
Create Date: 2026-08-26

- class 增加 cohort_label(届/毕业年,如 2029),与组织架构 grade_group 的 cohort_label 同义
- 回填:按「N届高X年级部」组织单元推导现有班级的届
- 唯一约束升级:(tenant_id, grade_id, name) → (tenant_id, grade_id, cohort_label, name),
  允许不同届的同名班级共存(如 2029届高一(1)班 与 2030届高一(1)班)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "5f2a8c4e7b1d"
down_revision: Union[str, Sequence[str], None] = "4e9c2b7d1f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(name: str) -> bool:
    return bool(op.get_bind().execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name},
    ).scalar())


def upgrade() -> None:
    op.execute("ALTER TABLE class ADD COLUMN IF NOT EXISTS cohort_label VARCHAR(30)")
    # 回填:届从「N届高X年级部」单元名称提取(单元 cohort_label 字段历史数据语义不一,不可信)
    op.execute("""
        UPDATE class cl SET cohort_label = substring(ou.name from '([0-9]{4})届')
        FROM grade g
        JOIN organizationunit ou ON ou.tenant_id = g.tenant_id
            AND ou.unit_type = 'grade_group'
            AND ou.status = 'active'
            AND ou.name LIKE CASE g.level WHEN 1 THEN '%高一%' WHEN 2 THEN '%高二%' ELSE '%高三%' END
        WHERE cl.grade_id = g.id AND cl.cohort_label IS NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_class_cohort_label ON class (cohort_label)")
    if _constraint_exists("uq_class_grade_name"):
        op.drop_constraint("uq_class_grade_name", "class", type_="unique")
    if not _constraint_exists("uq_class_grade_cohort_name"):
        op.create_unique_constraint(
            "uq_class_grade_cohort_name", "class",
            ["tenant_id", "grade_id", "cohort_label", "name"],
        )


def downgrade() -> None:
    if _constraint_exists("uq_class_grade_cohort_name"):
        op.drop_constraint("uq_class_grade_cohort_name", "class", type_="unique")
    if not _constraint_exists("uq_class_grade_name"):
        op.create_unique_constraint("uq_class_grade_name", "class", ["tenant_id", "grade_id", "name"])
    op.execute("DROP INDEX IF EXISTS ix_class_cohort_label")
    op.execute("ALTER TABLE class DROP COLUMN IF EXISTS cohort_label")
