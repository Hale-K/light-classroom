"""Scope administrative-class names by academic year and term.

The class list is isolated by academic year and term. Keep the historical
constraint name, but include both scope columns so a second-term class can
reuse the same name as its first-term counterpart.
"""
from alembic import op


revision = "u1d3e5f7a9b0"
down_revision = "t0c2d4e6f8a0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_class_grade_cohort_name", "class", type_="unique")
    op.create_unique_constraint(
        "uq_class_grade_cohort_name",
        "class",
        ["tenant_id", "grade_id", "cohort_label", "academic_year", "term", "name"],
    )


def downgrade():
    op.drop_constraint("uq_class_grade_cohort_name", "class", type_="unique")
    op.create_unique_constraint(
        "uq_class_grade_cohort_name",
        "class",
        ["tenant_id", "grade_id", "cohort_label", "name"],
    )
