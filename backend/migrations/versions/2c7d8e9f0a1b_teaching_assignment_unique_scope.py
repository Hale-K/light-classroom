"""unique constraint on teachingassignment (class, subject, year, term)

Revision ID: 2c7d8e9f0a1b
Revises: 1a2b3c4d5e6f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2c7d8e9f0a1b"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 防御性去重：同一 (tenant, class, subject, year, term) 只保留最早一行
    op.execute("""
        DELETE FROM teachingassignment ta
        USING teachingassignment keep
        WHERE keep.id < ta.id
          AND keep.tenant_id = ta.tenant_id
          AND keep.class_id = ta.class_id
          AND keep.subject_id = ta.subject_id
          AND keep.academic_year = ta.academic_year
          AND keep.term = ta.term
    """)
    op.create_unique_constraint(
        "uq_teachingassignment_scope",
        "teachingassignment",
        ["tenant_id", "class_id", "subject_id", "academic_year", "term"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_teachingassignment_scope", "teachingassignment", type_="unique")
