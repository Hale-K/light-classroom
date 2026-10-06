"""Persist student administrative-class membership by academic scope."""
from alembic import op


revision = "y5b7d9f1a3c5"
down_revision = "x4a6b8c0d2e4"
branch_labels = None
depends_on = None


def upgrade():
    from app.models.org import StudentClassMembership

    StudentClassMembership.__table__.create(op.get_bind(), checkfirst=True)
    op.execute("""
        INSERT INTO studentclassmembership
            (tenant_id, student_id, class_id, grade_id, cohort_label, academic_year, term, status, created_at, updated_at)
        SELECT s.tenant_id, s.id, c.id, c.grade_id, COALESCE(c.cohort_label, ''), c.academic_year, c.term,
               'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM student s
        JOIN class c ON c.id = s.class_id AND c.tenant_id = s.tenant_id
        WHERE s.class_id IS NOT NULL AND c.cohort_label IS NOT NULL
        ON CONFLICT (tenant_id, student_id, cohort_label, academic_year, term, grade_id)
        DO UPDATE SET class_id = EXCLUDED.class_id, status = 'active', updated_at = CURRENT_TIMESTAMP
    """)


def downgrade():
    op.drop_table("studentclassmembership")
