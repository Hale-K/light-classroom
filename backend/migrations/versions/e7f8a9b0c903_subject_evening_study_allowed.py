"""add subject eligibility for main-subject evening study"""

from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c903"
down_revision = "d4e6a8b0c902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column(
            "evening_study_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否允许安排为主课晚自习",
        ),
    )


def downgrade() -> None:
    op.drop_column("subject", "evening_study_allowed")
