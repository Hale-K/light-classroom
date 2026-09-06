"""remove the duplicate teacher home menu"""
from alembic import op
import sqlalchemy as sa

revision = "j9f3b5c7d1e2"
down_revision = "i8e2f4a6b9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM menu_permission WHERE menu_key = :key"), {"key": "teacher-home"})
    conn.execute(sa.text("DELETE FROM menu WHERE key = :key"), {"key": "teacher-home"})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv,
                          group_key, group_title, group_icon, group_sort)
        SELECT 'teacher-home', '首页', '/dashboard', 'home', 10, TRUE, 'teacher',
               'teacher-workbench', '教师工作台', 'school', 5
        WHERE NOT EXISTS (SELECT 1 FROM menu WHERE key = 'teacher-home')
    """))
