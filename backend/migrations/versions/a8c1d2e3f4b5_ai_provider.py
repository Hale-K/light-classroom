"""ai provider table and menu

Revision ID: a8c1d2e3f4b5
Revises: c3d4e5f6a7b8, a3b4c5d6e7f8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8c1d2e3f4b5"
down_revision: Union[str, Sequence[str], None] = ("c3d4e5f6a7b8", "a3b4c5d6e7f8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False, server_default="OPENAI"),
        sa.Column("base_url", sa.String(length=300), nullable=False),
        sa.Column("api_key", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("chat_model", sa.String(length=120), nullable=True),
        sa.Column("vision_model", sa.String(length=120), nullable=True),
        sa.Column("image_model", sa.String(length=120), nullable=True),
        sa.Column("video_model", sa.String(length=120), nullable=True),
        sa.Column("audio_model", sa.String(length=120), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remark", sa.String(length=200), nullable=True),
        sa.Column("last_test_status", sa.Integer(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_ai_provider_tenant_name"),
    )
    op.execute(
        """
        INSERT INTO permission (code, name, module, sort)
        VALUES
          ('ai_provider:view', '查看大模型服务商', '服务商管理', 90),
          ('ai_provider:manage', '配置大模型服务商', '服务商管理', 91)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort)
        VALUES ('ai-providers', '服务商管理', '/ai-providers', 'cloud', 15, TRUE, 'director', NULL, 'school-affairs', '学籍教务', 'file-text', 20)
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO menu_permission (menu_key, permission_id)
        SELECT 'ai-providers', p.id FROM permission p
        WHERE p.code IN ('ai_provider:view', 'ai_provider:manage')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO rbac_role_permission_template (role_code, permission_code)
        VALUES
          ('school_admin', 'ai_provider:view'),
          ('school_admin', 'ai_provider:manage')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("ai_provider")
