"""merge exam room catalog and seat layout

Revision ID: d49fb728a510
Revises: b5f4d9c2a781, c38ea617f409
Create Date: 2026-08-24
"""
from typing import Sequence, Union


revision: str = "d49fb728a510"
down_revision: Union[str, Sequence[str], None] = ("b5f4d9c2a781", "c38ea617f409")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
