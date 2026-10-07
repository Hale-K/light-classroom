"""Add academic term to exam records used by exam scheduling."""
from alembic import op
import sqlalchemy as sa

revision = "a7d9e1f3b5c7"
down_revision = "z6c8e0f2a4b6"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("exam")}
    if "term" not in columns:
        op.add_column("exam", sa.Column("term", sa.String(length=20), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("exam", "term")
