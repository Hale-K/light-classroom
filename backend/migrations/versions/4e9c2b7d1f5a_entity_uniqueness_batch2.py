"""第二批唯一性约束：RBAC 关联表 / 配置 / 登录账号 / 课表时段 / 画像与错题 / 考试日程

Revision ID: 4e9c2b7d1f5a
Revises: 3d8f1a2b6c4d
Create Date: 2026-08-26

- userrole / rolepermission / rolemenu: 关联表防重复授权
- tenantconfig: (tenant_id, config_key) 配置键唯一，保证按 key 覆盖语义
- tenant(code) / permission(code) / platformadmin(username): 模型已声明 unique 但从未迁移
- user: (tenant_id, phone) 登录账号租户内唯一
- schedule: (tenant_id, academic_year, term, class_id, weekday, period) 同一时段一节课
- studentprofile: (tenant_id, student_id, knowledge_point_id) 每知识点一条画像
- wrongquestion: (tenant_id, student_id, question_id) 错题去重（wrong_count 累加）
- examschedule: (exam_id, grade_id, session_index) 同场考试同年级同场次一份卷
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "4e9c2b7d1f5a"
down_revision: Union[str, Sequence[str], None] = "3d8f1a2b6c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINTS: list[tuple[str, str, list[str]]] = [
    ("userrole", "uq_userrole_user_role", ["user_id", "role_id"]),
    ("rolepermission", "uq_rolepermission_role_perm", ["role_id", "permission_id"]),
    ("rolemenu", "uq_rolemenu_role_menu", ["role_id", "menu_id"]),
    ("tenantconfig", "uq_tenantconfig_tenant_key", ["tenant_id", "config_key"]),
    ("tenant", "uq_tenant_code", ["code"]),
    ("permission", "uq_permission_code", ["code"]),
    ("platformadmin", "uq_platformadmin_username", ["username"]),
    ("user", "uq_user_tenant_phone", ["tenant_id", "phone"]),
    ("schedule", "uq_schedule_class_slot", ["tenant_id", "academic_year", "term", "class_id", "weekday", "period"]),
    ("studentprofile", "uq_studentprofile_student_kp", ["tenant_id", "student_id", "knowledge_point_id"]),
    ("wrongquestion", "uq_wrongquestion_student_question", ["tenant_id", "student_id", "question_id"]),
    ("examschedule", "uq_examschedule_grade_session", ["exam_id", "grade_id", "session_index"]),
]


def _create_uq(table: str, name: str, cols: list[str]) -> None:
    bind = op.get_bind()
    exists = bind.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).scalar()
    if not exists:
        op.create_unique_constraint(name, table, cols)


def upgrade() -> None:
    for table, name, cols in CONSTRAINTS:
        _create_uq(table, name, cols)


def downgrade() -> None:
    for table, name, _cols in reversed(CONSTRAINTS):
        op.drop_constraint(name, table, type_="unique")
