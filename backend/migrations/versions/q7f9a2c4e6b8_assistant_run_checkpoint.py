"""Persist assistant Supervisor checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "q7f9a2c4e6b8"
down_revision = "p6e8f1a3c5d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_run", sa.Column("checkpoint", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.alter_column("ai_run", "checkpoint", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_run", "checkpoint")
