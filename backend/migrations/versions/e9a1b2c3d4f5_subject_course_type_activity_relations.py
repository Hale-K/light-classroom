"""classify activity courses and allow assignments without a teacher

Revision ID: e9a1b2c3d4f5
Revises: e8a9b0c1d2e3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9a1b2c3d4f5"
down_revision: Union[str, Sequence[str], None] = "e8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column(
            "course_type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'subject'"),
            comment="subject=学科课；activity=活动课",
        ),
    )
    op.alter_column(
        "teachingassignment",
        "teacher_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "teachingassignment",
        "teacher_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("subject", "course_type")
