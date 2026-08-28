"""add grade binding to organization units

Revision ID: 9b3e7a1c2d44
Revises: 8a2c1d7e4b90
"""
from alembic import op
import sqlalchemy as sa

revision = "9b3e7a1c2d44"
down_revision = "8a2c1d7e4b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizationunit", sa.Column("grade_id", sa.Integer(), nullable=True))
    op.create_index("ix_organizationunit_grade_id", "organizationunit", ["grade_id"])
    op.create_foreign_key(
        "fk_organizationunit_grade_id", "organizationunit", "grade",
        ["grade_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_organizationunit_grade_id", "organizationunit", type_="foreignkey")
    op.drop_index("ix_organizationunit_grade_id", table_name="organizationunit")
    op.drop_column("organizationunit", "grade_id")
