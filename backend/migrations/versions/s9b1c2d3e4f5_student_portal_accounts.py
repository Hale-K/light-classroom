"""Add isolated student portal credentials."""
from alembic import op
import sqlalchemy as sa

revision = "s9b1c2d3e4f5"
down_revision = "r8a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("studentcredential"):
        return
    op.create_table(
        "studentcredential",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("student.id", ondelete="CASCADE"), nullable=False),
        sa.Column("login_name", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "student_id", name="uq_studentcredential_student"),
        sa.UniqueConstraint("tenant_id", "login_name", name="uq_studentcredential_login"),
    )
    for name, column in [
        ("tenant_id", "tenant_id"), ("student_id", "student_id"),
        ("login_name", "login_name"), ("status", "status"),
    ]:
        op.create_index(f"ix_studentcredential_{name}", "studentcredential", [column])


def downgrade():
    op.drop_table("studentcredential")
