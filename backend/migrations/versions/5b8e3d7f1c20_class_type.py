"""Add configurable class type for room planning."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b8e3d7f1c20"
down_revision: Union[str, Sequence[str], None] = "4a7d2c9e6b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("class", sa.Column("class_type", sa.String(length=30), nullable=False, server_default="regular"))
    op.create_index("ix_class_class_type", "class", ["class_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_class_class_type", table_name="class")
    op.drop_column("class", "class_type")
