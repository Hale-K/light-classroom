"""add seat layout

Revision ID: b5f4d9c2a781
Revises: b27d9a51c308
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5f4d9c2a781"
down_revision: Union[str, Sequence[str], None] = "b27d9a51c308"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    layout_enum = sa.Enum("normal", "snake", name="seatlayout")
    layout_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "seatarrangement",
        sa.Column(
            "layout",
            layout_enum,
            nullable=False,
            server_default="normal",
        ),
    )


def downgrade() -> None:
    op.drop_column("seatarrangement", "layout")
    sa.Enum("normal", "snake", name="seatlayout").drop(op.get_bind(), checkfirst=True)
