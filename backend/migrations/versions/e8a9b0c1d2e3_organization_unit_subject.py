"""bind subject groups to tenant-owned subjects"""

from alembic import op
import sqlalchemy as sa


revision = "e8a9b0c1d2e3"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("organizationunit")}
    if "subject_id" not in columns:
        op.add_column(
            "organizationunit",
            sa.Column("subject_id", sa.Integer(), nullable=True, comment="学科组关联的租户科目"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("organizationunit")}
    if "ix_organizationunit_subject_id" not in indexes:
        op.create_index("ix_organizationunit_subject_id", "organizationunit", ["subject_id"], unique=False)
    foreign_keys = {foreign_key["name"] for foreign_key in sa.inspect(bind).get_foreign_keys("organizationunit")}
    if "fk_organizationunit_subject_id" not in foreign_keys:
        op.create_foreign_key(
            "fk_organizationunit_subject_id",
            "organizationunit",
            "subject",
            ["subject_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    # One-time, tenant-safe backfill for legacy names. Runtime logic never matches names.
    op.execute(sa.text("""
        UPDATE organizationunit AS ou
        SET subject_id = s.id
        FROM subject AS s
        WHERE ou.unit_type = 'subject_group'
          AND ou.subject_id IS NULL
          AND s.tenant_id = ou.tenant_id
          AND trim(regexp_replace(ou.name, '教研组$', '')) = s.name
    """))


def downgrade() -> None:
    op.drop_constraint("fk_organizationunit_subject_id", "organizationunit", type_="foreignkey")
    op.drop_index("ix_organizationunit_subject_id", table_name="organizationunit")
    op.drop_column("organizationunit", "subject_id")
