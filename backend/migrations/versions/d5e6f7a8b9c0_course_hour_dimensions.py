"""add weekday and Saturday dimensions to course-hour plans"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "weekday_periods" not in columns:
        op.add_column(
            "coursehourplan",
            sa.Column("weekday_periods", sa.Float(), nullable=False, server_default=sa.text("0")),
        )
    if "saturday_periods" not in columns:
        op.add_column(
            "coursehourplan",
            sa.Column("saturday_periods", sa.Float(), nullable=False, server_default=sa.text("0")),
        )
    # Preserve existing records for schools that used the old single total field.
    bind.execute(sa.text(
        "UPDATE coursehourplan SET weekday_periods = weekly_periods "
        "WHERE weekday_periods = 0 AND saturday_periods = 0"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "saturday_periods" in columns:
        op.drop_column("coursehourplan", "saturday_periods")
    if "weekday_periods" in columns:
        op.drop_column("coursehourplan", "weekday_periods")
