"""menu/permission catalog columns for DB-backed RBAC

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("permission") as batch:
        batch.add_column(sa.Column("sort", sa.Integer(), nullable=False, server_default="0"))

    with op.batch_alter_table("menu") as batch:
        batch.add_column(sa.Column("key", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("roles_csv", sa.String(length=255), nullable=False, server_default=""))
        batch.add_column(sa.Column("required_capability", sa.String(length=50), nullable=True))
        batch.add_column(sa.Column("group_key", sa.String(length=50), nullable=False, server_default="other"))
        batch.add_column(sa.Column("group_title", sa.String(length=50), nullable=False, server_default="其他"))
        batch.add_column(sa.Column("group_icon", sa.String(length=50), nullable=False, server_default="grid"))
        batch.add_column(sa.Column("group_sort", sa.Integer(), nullable=False, server_default="100"))

    # 已有空表可直接加唯一约束；若有脏数据需先清洗
    op.execute("UPDATE menu SET key = 'legacy_' || id::text WHERE key IS NULL")
    with op.batch_alter_table("menu") as batch:
        batch.alter_column("key", existing_type=sa.String(length=50), nullable=False)
        batch.create_index("ix_menu_key", ["key"], unique=False)
        batch.create_index("ix_menu_group_key", ["group_key"], unique=False)
        batch.create_unique_constraint("uq_menu_key", ["key"])


def downgrade() -> None:
    with op.batch_alter_table("menu") as batch:
        batch.drop_constraint("uq_menu_key", type_="unique")
        batch.drop_index("ix_menu_group_key")
        batch.drop_index("ix_menu_key")
        batch.drop_column("group_sort")
        batch.drop_column("group_icon")
        batch.drop_column("group_title")
        batch.drop_column("group_key")
        batch.drop_column("required_capability")
        batch.drop_column("roles_csv")
        batch.drop_column("enabled")
        batch.drop_column("key")

    with op.batch_alter_table("permission") as batch:
        batch.drop_column("sort")
