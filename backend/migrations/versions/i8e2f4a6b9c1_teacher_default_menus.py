"""add the default teacher workbench menus

Revision ID: i8e2f4a6b9c1
Revises: h7d1e3f5a9b2
"""
from alembic import op
import sqlalchemy as sa

revision = "i8e2f4a6b9c1"
down_revision = "h7d1e3f5a9b2"
branch_labels = None
depends_on = None


TEACHER_MENUS = (
    ("teacher-courses", "课程", "/scheduling", "book", 20),
    ("teacher-preparation", "备课", "/file-center", "edit", 30),
    ("teacher-homework", "作业", "/exams", "clipboard", 40),
    ("teacher-grades", "成绩", "/teacher-grades", "chart", 50),
    ("teacher-students", "学生", "/students", "user", 60),
    ("teacher-classes", "班级", "/classes", "users", 70),
    ("teacher-research", "教研", "/meetings", "school", 80),
    ("teacher-notices", "通知", "/teacher-notices", "message", 90),
)


def upgrade() -> None:
    conn = op.get_bind()
    update_statement = sa.text("""
        UPDATE menu SET
            name = :name, path = :path, icon = :icon, sort = :sort,
            enabled = TRUE, roles_csv = 'teacher', required_capability = NULL,
            group_key = 'teacher-workbench', group_title = '教师工作台',
            group_icon = 'school', group_sort = 5
        WHERE key = :key
    """)
    insert_statement = sa.text("""
        INSERT INTO menu
            (key, name, path, icon, sort, enabled, roles_csv, required_capability,
             group_key, group_title, group_icon, group_sort)
        SELECT
            :key, :name, :path, :icon, :sort, TRUE, 'teacher', NULL,
            'teacher-workbench', '教师工作台', 'school', 5
        WHERE NOT EXISTS (SELECT 1 FROM menu WHERE key = CAST(:key AS varchar))
    """)
    for key, name, path, icon, sort in TEACHER_MENUS:
        params = {"key": key, "name": name, "path": path, "icon": icon, "sort": sort}
        conn.execute(update_statement, params)
        conn.execute(insert_statement, params)


def downgrade() -> None:
    keys = [item[0] for item in TEACHER_MENUS]
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM menu_permission WHERE menu_key IN :keys").bindparams(sa.bindparam("keys", expanding=True)), {"keys": keys})
    conn.execute(sa.text("DELETE FROM menu WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)), {"keys": keys})
