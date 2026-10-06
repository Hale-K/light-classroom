"""Add semester-scoped walk subject hours and explicit class overrides."""
from pathlib import Path
from alembic import op

revision = "v2e4f6a8b0c1"
down_revision = "u1d3e5f7a9b0"
branch_labels = None
depends_on = None


def upgrade():
    # 同一份可重复执行 SQL 同时支持手动部署及开发环境 create_all 后迁移。
    sql = Path(__file__).resolve().parents[3] / "db" / "schema" / "teaching_subject_hour_plan.sql"
    for statement in sql.read_text(encoding="utf-8").split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    op.drop_index("ix_teachingclass_hour_plan_id", table_name="teachingclass")
    op.drop_column("teachingclass", "hours_overridden")
    op.drop_column("teachingclass", "hour_plan_id")
    op.drop_table("teaching_subject_hour_plan")
