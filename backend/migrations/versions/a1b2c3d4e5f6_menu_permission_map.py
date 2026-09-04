"""menu_permission: DB-backed menu visibility permission map

Revision ID: a1b2c3d4e5f6
Revises: f2b3c4d5e6f7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("menu_key", sa.String(length=50), nullable=False),
        sa.Column("permission_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("menu_key", "permission_id", name="uq_menu_permission_key_perm"),
        comment="菜单-权限点映射",
    )
    op.create_index(
        op.f("ix_menu_permission_menu_key"),
        "menu_permission",
        ["menu_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_menu_permission_permission_id"),
        "menu_permission",
        ["permission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_permission_permission_id"), table_name="menu_permission")
    op.drop_index(op.f("ix_menu_permission_menu_key"), table_name="menu_permission")
    op.drop_table("menu_permission")
