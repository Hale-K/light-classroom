"""file transfer job for file center

Revision ID: a3b4c5d6e7f8
Revises: f2b3c4d5e6f7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_transfer_job",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("job_type", sa.String(length=64), nullable=False, index=True),
        sa.Column("direction", sa.String(length=16), nullable=False, index=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued", index=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operator_id", sa.Integer(), nullable=True, index=True),
        sa.Column("operator_name", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("scope", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # menu: 文件中心
    op.execute(
        """
        INSERT INTO permission (code, name, module, sort)
        VALUES ('file_center:view', '查看文件中心', '文件中心', 80)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort)
        VALUES ('file-center', '文件中心', '/file-center', 'upload', 30, TRUE, 'director,academic_director', NULL, 'teaching', '教学安排', 'book', 70)
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO menu_permission (menu_key, permission_id)
        SELECT 'file-center', p.id FROM permission p WHERE p.code = 'file_center:view'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO rbac_role_permission_template (role_code, permission_code)
        VALUES
          ('school_admin', 'file_center:view'),
          ('academic_director', 'file_center:view')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("file_transfer_job")
