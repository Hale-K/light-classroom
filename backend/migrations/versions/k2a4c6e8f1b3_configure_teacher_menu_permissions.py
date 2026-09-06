"""configure permission bindings for teacher workbench menus"""
from alembic import op
import sqlalchemy as sa

revision = "k2a4c6e8f1b3"
down_revision = "j9f3b5c7d1e2"
branch_labels = None
depends_on = None

MENU_PERMISSIONS = {
    "teacher-courses": "scheduling:view", "teacher-preparation": "file_center:view",
    "teacher-homework": "exam:view", "teacher-grades": "grading:view",
    "teacher-students": "students:view", "teacher-classes": "classes:view",
    "teacher-research": "meetings:view", "teacher-notices": "meetings:view",
}


def upgrade() -> None:
    conn = op.get_bind()
    statement = sa.text("""
        INSERT INTO menu_permission (menu_key, permission_id)
        SELECT CAST(:menu_key AS varchar), p.id FROM permission p
        WHERE p.code = :permission_code
          AND EXISTS (SELECT 1 FROM menu m WHERE m.key = CAST(:menu_key AS varchar))
          AND NOT EXISTS (
              SELECT 1 FROM menu_permission mp
              WHERE mp.menu_key = CAST(:menu_key AS varchar) AND mp.permission_id = p.id
          )
    """)
    for menu_key, permission_code in MENU_PERMISSIONS.items():
        conn.execute(statement, {"menu_key": menu_key, "permission_code": permission_code})


def downgrade() -> None:
    conn = op.get_bind()
    statement = sa.text("""
        DELETE FROM menu_permission mp USING permission p
        WHERE mp.permission_id = p.id AND mp.menu_key = CAST(:menu_key AS varchar) AND p.code = :permission_code
    """)
    for menu_key, permission_code in MENU_PERMISSIONS.items():
        conn.execute(statement, {"menu_key": menu_key, "permission_code": permission_code})
