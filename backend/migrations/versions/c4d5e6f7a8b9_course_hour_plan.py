"""add tenant-scoped class course-hour plans"""

from alembic import op
import sqlalchemy as sa


revision = "c4d5e6f7a8b9"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Development startup runs SQLModel.metadata.create_all(), so this table
    # may already exist before Alembic records the revision. In that case the
    # model-created indexes/foreign keys are already present; keep the
    # migration idempotent and only advance the revision.
    if "coursehourplan" in inspector.get_table_names():
        return
    op.create_table(
        "coursehourplan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("term", sa.String(length=20), nullable=False, server_default="1"),
        sa.Column("weekly_periods", sa.Float(), nullable=False, server_default="4"),
        sa.Column(
            "week_parity",
            sa.Enum("all", "odd", "even", name="weekparity"),
            nullable=False,
            server_default="all",
        ),
        sa.ForeignKeyConstraint(["class_id"], ["class.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subject.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "academic_year", "term", "class_id", "subject_id", "week_parity",
            name="uq_coursehourplan_scope",
        ),
        comment="班级课时方案",
    )
    op.create_index("ix_coursehourplan_tenant_id", "coursehourplan", ["tenant_id"], unique=False)
    op.create_index("ix_coursehourplan_class_id", "coursehourplan", ["class_id"], unique=False)
    op.create_index("ix_coursehourplan_subject_id", "coursehourplan", ["subject_id"], unique=False)
    op.create_index("ix_coursehourplan_academic_year", "coursehourplan", ["academic_year"], unique=False)
    op.create_index("ix_coursehourplan_term", "coursehourplan", ["term"], unique=False)
    op.create_index("ix_coursehourplan_week_parity", "coursehourplan", ["week_parity"], unique=False)
    op.create_check_constraint(
        "ck_coursehourplan_week_parity",
        "coursehourplan",
        "week_parity IN ('all', 'odd', 'even')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_coursehourplan_week_parity", "coursehourplan", type_="check")
    op.drop_index("ix_coursehourplan_week_parity", table_name="coursehourplan")
    op.drop_index("ix_coursehourplan_term", table_name="coursehourplan")
    op.drop_index("ix_coursehourplan_academic_year", table_name="coursehourplan")
    op.drop_index("ix_coursehourplan_subject_id", table_name="coursehourplan")
    op.drop_index("ix_coursehourplan_class_id", table_name="coursehourplan")
    op.drop_index("ix_coursehourplan_tenant_id", table_name="coursehourplan")
    op.drop_table("coursehourplan")
