"""route teacher courses to the teacher-only page

Revision ID: m4c6e8a1b3d5
Revises: l3b5d7f9a2c4
"""
from alembic import op
import sqlalchemy as sa

revision = "m4c6e8a1b3d5"
down_revision = "l3b5d7f9a2c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE menu SET path = '/teacher-courses' WHERE key = 'teacher-courses'")
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE menu SET path = '/scheduling' WHERE key = 'teacher-courses'")
    )
