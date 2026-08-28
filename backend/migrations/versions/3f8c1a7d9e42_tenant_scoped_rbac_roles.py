"""tenant scoped RBAC roles

Revision ID: 3f8c1a7d9e42
Revises: 2d6a8f04b731
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "3f8c1a7d9e42"
down_revision = "2d6a8f04b731"
branch_labels = None
depends_on = None

BUILTIN_CODES = ("school_admin", "academic_director", "head_teacher", "subject_teacher")


def upgrade() -> None:
    op.add_column("role", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.drop_index("ix_role_code", table_name="role")
    op.create_index("ix_role_code", "role", ["code"], unique=False)
    op.create_index("ix_role_tenant_id", "role", ["tenant_id"], unique=False)
    op.create_unique_constraint("uq_role_tenant_code", "role", ["tenant_id", "code"])

    connection = op.get_bind()
    tenant_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM tenant"))]
    for tenant_id in tenant_ids:
        for code in BUILTIN_CODES:
            source = connection.execute(sa.text(
                "SELECT id, name, description FROM role "
                "WHERE tenant_id IS NULL AND code = :code ORDER BY id LIMIT 1"
            ), {"code": code}).first()
            if source is None:
                continue
            target_id = connection.execute(sa.text(
                "INSERT INTO role (tenant_id, code, name, description) "
                "VALUES (:tenant_id, :code, :name, :description) RETURNING id"
            ), {
                "tenant_id": tenant_id,
                "code": code,
                "name": source.name,
                "description": source.description,
            }).scalar_one()
            connection.execute(sa.text(
                "INSERT INTO rolepermission (role_id, permission_id) "
                "SELECT :target_id, permission_id FROM rolepermission WHERE role_id = :source_id"
            ), {"target_id": target_id, "source_id": source.id})

    connection.execute(sa.text(
        'UPDATE userrole AS ur SET role_id = target.id '
        'FROM "user" AS u, role AS source, role AS target '
        'WHERE ur.user_id = u.id AND ur.role_id = source.id '
        'AND source.tenant_id IS NULL AND target.tenant_id = u.tenant_id '
        'AND target.code = source.code'
    ))


def downgrade() -> None:
    connection = op.get_bind()
    custom_count = connection.execute(sa.text(
        "SELECT count(*) FROM role WHERE tenant_id IS NOT NULL AND code NOT IN "
        "('school_admin', 'academic_director', 'head_teacher', 'subject_teacher')"
    )).scalar_one()
    if custom_count:
        raise RuntimeError("Cannot downgrade while tenant custom roles exist")

    connection.execute(sa.text(
        'UPDATE userrole AS ur SET role_id = source.id '
        'FROM "user" AS u, role AS target, role AS source '
        'WHERE ur.user_id = u.id AND ur.role_id = target.id '
        'AND target.tenant_id = u.tenant_id AND source.tenant_id IS NULL '
        'AND source.code = target.code'
    ))
    connection.execute(sa.text(
        "DELETE FROM rolepermission WHERE role_id IN "
        "(SELECT id FROM role WHERE tenant_id IS NOT NULL)"
    ))
    connection.execute(sa.text("DELETE FROM role WHERE tenant_id IS NOT NULL"))

    op.drop_constraint("uq_role_tenant_code", "role", type_="unique")
    op.drop_index("ix_role_tenant_id", table_name="role")
    op.drop_index("ix_role_code", table_name="role")
    op.drop_column("role", "tenant_id")
    op.create_index("ix_role_code", "role", ["code"], unique=True)
