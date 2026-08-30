"""scope school-owned subjects by tenant while keeping shared subjects"""

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c903"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subject",
        sa.Column("tenant_id", sa.Integer(), nullable=True, comment="租户 ID；为空表示系统公共科目"),
    )
    op.create_index("ix_subject_tenant_id", "subject", ["tenant_id"], unique=False)
    # The original table was created by SQLModel, so PostgreSQL named this
    # constraint ``subject_name_key`` instead of the name used by the model.
    # Keep this migration safe for both databases.
    op.execute("ALTER TABLE subject DROP CONSTRAINT IF EXISTS uq_subject_name")
    op.execute("ALTER TABLE subject DROP CONSTRAINT IF EXISTS subject_name_key")
    op.create_unique_constraint("uq_subject_tenant_name", "subject", ["tenant_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_subject_tenant_name", "subject", type_="unique")
    op.create_unique_constraint("uq_subject_name", "subject", ["name"])
    op.drop_index("ix_subject_tenant_id", table_name="subject")
    op.drop_column("subject", "tenant_id")
