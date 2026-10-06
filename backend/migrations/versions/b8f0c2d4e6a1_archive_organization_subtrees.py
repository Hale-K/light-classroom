"""Archive descendants and active appointments under previously archived units.

Revision ID: b8f0c2d4e6a1
Revises: a7d9f3b1c5e8
"""
from alembic import op


revision = "b8f0c2d4e6a1"
down_revision = "a7d9f3b1c5e8"
branch_labels = None
depends_on = None


_ARCHIVED_SUBTREE = """
WITH RECURSIVE archived_units(id, tenant_id) AS (
    SELECT id, tenant_id
    FROM organizationunit
    WHERE status = 'archived'
    UNION
    SELECT child.id, child.tenant_id
    FROM organizationunit AS child
    JOIN archived_units AS parent
      ON child.parent_id = parent.id
     AND child.tenant_id = parent.tenant_id
)
"""


def upgrade():
    bind = op.get_bind()
    # Repair archived parents created by older versions, which could leave active
    # children visible as roots. Keep all rows for historical lookups.
    bind.exec_driver_sql(
        _ARCHIVED_SUBTREE
        + "UPDATE organizationunit SET status = 'archived' "
          "WHERE id IN (SELECT id FROM archived_units)"
    )
    bind.exec_driver_sql(
        _ARCHIVED_SUBTREE
        + "UPDATE staffappointment SET status = 'archived' "
          "WHERE status = 'active' "
          "AND organization_unit_id IN (SELECT id FROM archived_units)"
    )


def downgrade():
    raise RuntimeError("Archived organization descendants and appointments cannot be safely reactivated automatically.")
