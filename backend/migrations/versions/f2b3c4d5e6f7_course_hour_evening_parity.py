"""add evening_parity so 0.5 evening is not inferred from daytime week_parity

Revision ID: f2b3c4d5e6f7
Revises: e9a1b2c3d4f5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "e9a1b2c3d4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "evening_parity" not in columns:
        op.add_column(
            "coursehourplan",
            sa.Column("evening_parity", sa.String(length=10), nullable=False, server_default="all"),
        )
    op.execute(
        """
        UPDATE coursehourplan
        SET evening_parity = CASE
            WHEN evening_periods_odd > 0 AND COALESCE(evening_periods_even, 0) = 0 THEN 'odd'
            WHEN evening_periods_even > 0 AND COALESCE(evening_periods_odd, 0) = 0 THEN 'even'
            WHEN evening_periods_odd > 0 AND evening_periods_even > 0 THEN 'either'
            ELSE 'all'
        END
        """
    )
    op.execute(
        """
        UPDATE coursehourplan AS ch
        SET evening_parity = 'all'
        FROM subject AS s
        WHERE s.id = ch.subject_id
          AND ch.evening_periods_odd > 0
          AND ch.evening_periods_even > 0
          AND s.name IN ('语文', '数学', '英语')
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("coursehourplan")}
    if "evening_parity" in columns:
        op.drop_column("coursehourplan", "evening_parity")
