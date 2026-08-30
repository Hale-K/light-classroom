"""add week parity to schedule items

Revision ID: b8d3f2a6c901
Revises: a7c4e9d1b2f0
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "b8d3f2a6c901"
down_revision = "a7c4e9d1b2f0"
branch_labels = None
depends_on = None


def _create_constraint_if_missing(name: str, columns: list[str]) -> None:
    """Create a unique constraint only when a retry did not already create it."""
    exists = op.get_bind().execute(sa.text(
        "SELECT 1 FROM pg_constraint WHERE conname = :name"
    ), {"name": name}).scalar()
    if not exists:
        op.create_unique_constraint(name, "schedule", columns)


def upgrade() -> None:
    weekparity = sa.Enum("all", "odd", "even", name="weekparity")
    weekparity.create(op.get_bind(), checkfirst=True)
    op.add_column("schedule", sa.Column(
        "week_parity",
        weekparity,
        nullable=False,
        server_default=sa.text("'all'::weekparity"),
        comment="周次: all=每周 odd=单周 even=双周",
    ))
    op.execute("UPDATE schedule SET week_parity = 'all' WHERE week_parity IS NULL")
    op.execute("ALTER TABLE schedule DROP CONSTRAINT IF EXISTS uq_schedule_class_slot")
    _create_constraint_if_missing(
        "uq_schedule_class_slot_parity",
        ["tenant_id", "academic_year", "term", "class_id", "weekday", "period", "week_parity"],
    )


def downgrade() -> None:
    op.execute("ALTER TABLE schedule DROP CONSTRAINT IF EXISTS uq_schedule_class_slot_parity")
    # odd/even rows collapse to one row when returning to the old one-slot-per-week schema.
    op.execute("""
        DELETE FROM schedule AS duplicate
        USING schedule AS kept
        WHERE duplicate.tenant_id = kept.tenant_id
          AND duplicate.academic_year = kept.academic_year
          AND duplicate.term = kept.term
          AND duplicate.class_id = kept.class_id
          AND duplicate.weekday = kept.weekday
          AND duplicate.period = kept.period
          AND duplicate.id > kept.id
    """)
    _create_constraint_if_missing(
        "uq_schedule_class_slot",
        ["tenant_id", "academic_year", "term", "class_id", "weekday", "period"],
    )
    op.drop_column("schedule", "week_parity")
    sa.Enum(name="weekparity").drop(op.get_bind(), checkfirst=True)
