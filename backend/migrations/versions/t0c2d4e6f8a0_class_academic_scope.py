"""Add academic year and term scope to administrative classes.

Existing classes predate term isolation. Their academic year is backfilled
from the tenant's current academic-year configuration and their legacy scope
is treated as the first term.
"""
from alembic import op
import sqlalchemy as sa


revision = "t0c2d4e6f8a0"
down_revision = "s9b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.add_column("class", sa.Column("academic_year", sa.String(length=20), nullable=True))
    op.add_column("class", sa.Column("term", sa.String(length=20), nullable=True))

    class_table = sa.table(
        "class",
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.Integer()),
        sa.column("academic_year", sa.String(20)),
        sa.column("term", sa.String(20)),
    )
    config_table = sa.table(
        "tenantconfig",
        sa.column("tenant_id", sa.Integer()),
        sa.column("config_key", sa.String(50)),
        sa.column("config_value", sa.JSON()),
    )

    configs = {}
    for tenant_id, config_value in bind.execute(
        sa.select(config_table.c.tenant_id, config_table.c.config_value).where(
            config_table.c.config_key == "academic_years",
        )
    ).all():
        configs[tenant_id] = config_value if isinstance(config_value, dict) else {}

    class_ids = [row.id for row in bind.execute(sa.select(class_table.c.id)).all()]
    for class_id in class_ids:
        tenant_id = bind.execute(
            sa.select(class_table.c.tenant_id).where(class_table.c.id == class_id)
        ).scalar_one()
        config = configs.get(tenant_id, {})
        academic_year = config.get("current_academic_year")
        if not isinstance(academic_year, str) or "-" not in academic_year:
            academic_year = "2026-2027"
        # Before term isolation all administrative classes represented the
        # first-term setup. Do not use the current UI term here: a migration
        # run after switching to term 2 must not relabel historical classes.
        term = "1"
        bind.execute(
            class_table.update().where(class_table.c.id == class_id).values(
                academic_year=academic_year,
                term=term,
            )
        )

    op.alter_column("class", "academic_year", nullable=False)
    op.alter_column("class", "term", nullable=False)
    op.create_index("ix_class_academic_year", "class", ["academic_year"])
    op.create_index("ix_class_term", "class", ["term"])


def downgrade():
    op.drop_index("ix_class_term", table_name="class")
    op.drop_index("ix_class_academic_year", table_name="class")
    op.drop_column("class", "term")
    op.drop_column("class", "academic_year")
