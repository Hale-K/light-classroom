"""Remove scan intake and meeting booking tables and RBAC entries.

Revision ID: z6c8e0f2a4b6
Revises: y5b7d9f1a3c5
"""
from alembic import op
import sqlalchemy as sa


revision = "z6c8e0f2a4b6"
down_revision = "y5b7d9f1a3c5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "room" in tables:
        room_columns = {column["name"] for column in inspector.get_columns("room")}
        if "is_meeting_enabled" in room_columns:
            op.drop_column("room", "is_meeting_enabled")

    # The feature and its associated records are explicitly out of scope.
    # Clear children before their parent tables are dropped below.
    for table in ("scanpage", "scanbatch", "roombooking", "meeting"):
        if table in tables:
            bind.execute(sa.text(f'DELETE FROM "{table}"'))

    # Clear dependent rows before their catalog entries.
    if "menu_permission" in tables and "permission" in tables and "menu" in tables:
        # Older catalogs used meetings:view to expose the teacher notices page.
        bind.execute(sa.text("""
            INSERT INTO menu_permission (menu_key, permission_id)
            SELECT 'teacher-notices', p.id
            FROM permission p
            WHERE p.code = 'teacher_menu:notices'
              AND EXISTS (SELECT 1 FROM menu WHERE key = 'teacher-notices')
            ON CONFLICT (menu_key, permission_id) DO NOTHING
        """))
        bind.execute(sa.text("""
            DELETE FROM menu_permission
            WHERE menu_key IN ('scans', 'meetings', 'teacher-research')
               OR permission_id IN (
                    SELECT id FROM permission
                    WHERE code LIKE 'scan:%' OR code LIKE 'meetings:%'
               )
        """))
    if "role_menu" in tables and "menu" in tables:
        bind.execute(sa.text("""
            DELETE FROM role_menu
            WHERE menu_id IN (SELECT id FROM menu WHERE key IN ('scans', 'meetings', 'teacher-research'))
        """))
    if "role_permission" in tables and "permission" in tables:
        bind.execute(sa.text("""
            DELETE FROM role_permission
            WHERE permission_id IN (
                SELECT id FROM permission WHERE code LIKE 'scan:%' OR code LIKE 'meetings:%'
            )
        """))
    if "rbac_role_permission_template" in tables:
        bind.execute(sa.text("""
            DELETE FROM rbac_role_permission_template
            WHERE permission_code LIKE 'scan:%' OR permission_code LIKE 'meetings:%'
        """))
    if "menu" in tables:
        bind.execute(sa.text("DELETE FROM menu WHERE key IN ('scans', 'meetings', 'teacher-research')"))
        bind.execute(sa.text("UPDATE menu SET name = '考试管理', icon = 'calendar' WHERE key = 'exams'"))
    if "menu_permission" in tables and "permission" in tables:
        bind.execute(sa.text("""
            DELETE FROM menu_permission
            WHERE menu_key = 'exams'
              AND permission_id IN (SELECT id FROM permission WHERE code LIKE 'paper:%')
        """))
        bind.execute(sa.text("""
            INSERT INTO menu_permission (menu_key, permission_id)
            SELECT 'exams', p.id
            FROM permission p
            WHERE p.code = 'exam:view'
              AND EXISTS (SELECT 1 FROM menu WHERE key = 'exams')
            ON CONFLICT (menu_key, permission_id) DO NOTHING
        """))
    if "permission" in tables:
        bind.execute(sa.text("DELETE FROM permission WHERE code LIKE 'scan:%' OR code LIKE 'meetings:%'"))

    # Drop children before their parent tables.
    for table in ("scanpage", "scanbatch", "roombooking", "meeting"):
        if table in tables:
            op.drop_table(table)


def downgrade():
    # Feature data and authorization catalog rows cannot be reconstructed.
    raise RuntimeError("This feature-removal migration is irreversible.")
