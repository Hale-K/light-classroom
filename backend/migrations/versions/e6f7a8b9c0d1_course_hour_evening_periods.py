"""add parity-specific evening-study periods to course-hour plans"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "evening_periods_odd" not in columns:
        op.add_column(
            "coursehourplan",
            sa.Column("evening_periods_odd", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if "evening_periods_even" not in columns:
        op.add_column(
            "coursehourplan",
            sa.Column("evening_periods_even", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "evening_periods_even" in columns:
        op.drop_column("coursehourplan", "evening_periods_even")
    if "evening_periods_odd" in columns:
        op.drop_column("coursehourplan", "evening_periods_odd")
