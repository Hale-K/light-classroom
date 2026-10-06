"""Remove paper-bank, question, submission and grading persistence.

Revision ID: a7d9f3b1c5e8
Revises: z6c8e0f2a4b6
"""
from alembic import op
import sqlalchemy as sa


revision = "a7d9f3b1c5e8"
down_revision = "z6c8e0f2a4b6"
branch_labels = None
depends_on = None


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def _drop_column_if_present(table, column):
    bind = op.get_bind()
    if table not in _tables(bind):
        return
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns(table)}
    if column not in columns:
        return
    for index in inspector.get_indexes(table):
        if column in index.get("column_names", []) and index.get("name"):
            op.drop_index(index["name"], table_name=table)
    for constraint in inspector.get_unique_constraints(table):
        if column in (constraint.get("column_names") or []) and constraint.get("name"):
            op.drop_constraint(constraint["name"], table, type_="unique")
    op.drop_column(table, column)


def upgrade():
    bind = op.get_bind()
    tables = _tables(bind)

    if "exam" in tables and "term" not in {item["name"] for item in sa.inspect(bind).get_columns("exam")}:
        op.add_column("exam", sa.Column("term", sa.String(length=20), nullable=False, server_default="1"))

    # Keep generated schedules and candidate seats; only remove their obsolete
    # paper identity. Exam, grade, subject and schedule links remain sufficient.
    for table in ("examschedule", "examroomassignment", "examcandidateassignment"):
        _drop_column_if_present(table, "paper_id")

    if "examcandidateassignment" in _tables(bind):
        inspector = sa.inspect(bind)
        for constraint in inspector.get_unique_constraints("examcandidateassignment"):
            if constraint.get("name") == "uq_examcandidate_paper_student":
                op.drop_constraint(constraint["name"], "examcandidateassignment", type_="unique")
        names = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("examcandidateassignment")}
        if "uq_examcandidate_subject_student" not in names:
            op.create_unique_constraint(
                "uq_examcandidate_subject_student",
                "examcandidateassignment",
                ["exam_id", "grade_id", "subject_id", "student_id"],
            )

    # The user requested full removal of paper/question/answer/grading data.
    # Drop child tables first so old response data cannot be orphaned.
    tables = _tables(bind)
    for table in ("answerscore", "submission", "question", "paper"):
        if table in tables:
            op.drop_table(table)

    tables = _tables(bind)
    for table, patterns in (
        ("role_permission", ("paper:%", "grading:%")),
        ("menu_permission", ("paper:%", "grading:%")),
        ("rbac_role_permission_template", ("paper:%", "grading:%")),
    ):
        if table not in tables:
            continue
        column = "permission_code" if table == "rbac_role_permission_template" else "permission_id"
        if table == "rbac_role_permission_template":
            bind.execute(sa.text(
                "DELETE FROM rbac_role_permission_template WHERE permission_code LIKE 'paper:%' OR permission_code LIKE 'grading:%'"
            ))
        elif "permission" in tables:
            bind.execute(sa.text(
                f"DELETE FROM {table} WHERE {column} IN (SELECT id FROM permission WHERE code LIKE 'paper:%' OR code LIKE 'grading:%')"
            ))
    if "permission" in _tables(bind):
        bind.execute(sa.text("DELETE FROM permission WHERE code LIKE 'paper:%' OR code LIKE 'grading:%'"))


def downgrade():
    raise RuntimeError("Paper-bank and grading data were deliberately deleted and cannot be restored.")
