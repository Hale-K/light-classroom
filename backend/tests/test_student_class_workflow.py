import pytest
from pydantic import ValidationError

from app.api.v1.org import (
    ClassAssignmentIn,
    GradeIn,
    StudentIn,
    StudentSimulationIn,
    add_existing_class_counts,
    count_students,
    create_grade,
)


def test_auto_assignment_preview_includes_existing_class_counts():
    class_rows = {
        101: {"student_count": 0, "male_count": 0, "female_count": 0},
        102: {"student_count": 0, "male_count": 0, "female_count": 0},
    }
    existing_students = [
        type("StudentRow", (), {"class_id": 101, "gender": "male"})(),
        type("StudentRow", (), {"class_id": 101, "gender": "female"})(),
        type("StudentRow", (), {"class_id": 102, "gender": "female"})(),
    ]

    add_existing_class_counts(class_rows, existing_students)

    assert class_rows[101]["student_count"] == 2
    assert class_rows[101]["male_count"] == 1
    assert class_rows[101]["female_count"] == 1
    assert class_rows[102]["student_count"] == 1


def test_student_record_can_exist_before_class_assignment():
    body = StudentIn(
        name="待分班学生",
        gender="male",
        student_no="G20260001",
        campus_id=1,
        grade_id=2,
    )
    assert body.class_id is None
    assert body.campus_id == 1
    assert body.grade_id == 2


def test_class_assignment_requires_at_least_one_student():
    with pytest.raises(ValidationError):
        ClassAssignmentIn(class_id=1, student_ids=[])


def test_students_can_be_assigned_or_returned_to_unassigned_pool():
    assigned = ClassAssignmentIn(class_id=3, student_ids=[1, 2])
    unassigned = ClassAssignmentIn(class_id=None, student_ids=[1, 2])
    assert assigned.class_id == 3
    assert unassigned.class_id is None


def test_student_simulation_requires_at_least_one_student():
    with pytest.raises(ValidationError):
        StudentSimulationIn(cohort_label="2026", grade_id=1, male_count=0, female_count=0)


def test_student_simulation_accepts_gender_counts():
    body = StudentSimulationIn(cohort_label="2026届", grade_id=1, male_count=12, female_count=18)
    assert body.male_count + body.female_count == 30


@pytest.mark.asyncio
async def test_student_count_is_scoped_to_current_school():
    class Result:
        @staticmethod
        def scalar_one():
            return 0

    class RecordingSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = RecordingSession()
    await count_students(session=session, user=object(), tenant_id=3)
    compiled = session.statement.compile()

    assert 3 in compiled.params.values()


@pytest.mark.asyncio
async def test_create_grade_normalizes_name_without_duplicate_constructor_kwargs():
    class Result:
        @staticmethod
        def scalar():
            return None

    class RecordingSession:
        added = None

        async def execute(self, statement):
            return Result()

        def add(self, value):
            self.added = value

        async def commit(self):
            pass

        async def refresh(self, value):
            pass

    session = RecordingSession()
    result = await create_grade(
        GradeIn(name="  高二年级  ", level=1, campus_id=3),
        session=session,
        user=object(),
        tenant_id=7,
    )

    assert session.added.name == "高二年级"
    assert result["data"]["name"] == "高二年级"
