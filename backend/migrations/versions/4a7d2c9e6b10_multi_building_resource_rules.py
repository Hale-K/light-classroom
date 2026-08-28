"""Allow one resource allocation rule to span multiple buildings."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4a7d2c9e6b10"
down_revision: Union[str, Sequence[str], None] = "3f8c1a7d9e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resourceallocationrule", sa.Column("building_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("resourceallocationrule", "building_ids")
