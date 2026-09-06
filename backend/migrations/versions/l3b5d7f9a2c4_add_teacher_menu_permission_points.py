"""add configurable teacher menu permission points

Revision ID: l3b5d7f9a2c4
Revises: k2a4c6e8f1b3
"""
from alembic import op
import sqlalchemy as sa

revision = "l3b5d7f9a2c4"
down_revision = "k2a4c6e8f1b3"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("teacher-courses", "teacher_menu:courses", "课程菜单", 10),
    ("teacher-preparation", "teacher_menu:preparation", "备课菜单", 20),
    ("teacher-homework", "teacher_menu:homework", "作业菜单", 30),
    ("teacher-grades", "teacher_menu:grades", "成绩菜单", 40),
    ("teacher-students", "teacher_menu:students", "学生菜单", 50),
    ("teacher-classes", "teacher_menu:classes", "班级菜单", 60),
    ("teacher-research", "teacher_menu:research", "教研菜单", 70),
    ("teacher-notices", "teacher_menu:notices", "通知菜单", 80),
)


def upgrade() -> None:
    conn = op.get_bind()
    insert_permission = sa.text("""
        INSERT INTO permission (module, name, code, sort)
        SELECT '教师工作台', :name, CAST(:code AS varchar), :sort
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = CAST(:code AS varchar))
    """)
    update_permission = sa.text("""
        UPDATE permission SET module = '教师工作台', name = :name, sort = :sort
        WHERE code = CAST(:code AS varchar)
    """)
    clear_bindings = sa.text("DELETE FROM menu_permission WHERE menu_key = CAST(:menu_key AS varchar)")
    bind_menu = sa.text("""
        INSERT INTO menu_permission (menu_key, permission_id)
        SELECT CAST(:menu_key AS varchar), id FROM permission
        WHERE code = CAST(:code AS varchar)
    """)
    for menu_key, code, name, sort in PERMISSIONS:
        params = {"menu_key": menu_key, "code": code, "name": name, "sort": sort}
        conn.execute(insert_permission, params)
        conn.execute(update_permission, params)
        conn.execute(clear_bindings, params)
        conn.execute(bind_menu, params)


def downgrade() -> None:
    conn = op.get_bind()
    for menu_key, code, _name, _sort in PERMISSIONS:
        conn.execute(sa.text("DELETE FROM menu_permission WHERE menu_key = CAST(:menu_key AS varchar)"), {"menu_key": menu_key})
        conn.execute(sa.text("DELETE FROM role_permission WHERE permission_id IN (SELECT id FROM permission WHERE code = CAST(:code AS varchar))"), {"code": code})
        conn.execute(sa.text("DELETE FROM permission WHERE code = CAST(:code AS varchar)"), {"code": code})
