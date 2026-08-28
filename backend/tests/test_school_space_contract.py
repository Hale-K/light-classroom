import pytest
from pydantic import ValidationError

from app.api.v1.facilities import CampusIn
from app.api.v1.org import ClassIn, GradeIn
from scripts.seed_campus_grade_classrooms import balanced_sizes


def test_campus_accepts_planned_student_capacity():
    campus = CampusIn(name="崇仁一中", student_capacity=5000)

    assert campus.student_capacity == 5000


def test_grade_can_be_scoped_to_a_campus():
    grade = GradeIn(name="高一年级", level=1, campus_id=7)

    assert grade.campus_id == 7


def test_administrative_class_can_bind_a_home_room_and_planned_size():
    administrative_class = ClassIn(
        grade_id=3,
        name="高一（1）班",
        campus_id=7,
        home_room_id=21,
        planned_student_count=45,
    )

    assert administrative_class.home_room_id == 21
    assert administrative_class.planned_student_count == 45


def test_planned_class_size_cannot_exceed_school_limit():
    with pytest.raises(ValidationError):
        ClassIn(
            grade_id=3,
            name="高一（1）班",
            campus_id=7,
            home_room_id=21,
            planned_student_count=46,
        )


@pytest.mark.parametrize(
    ("student_count", "class_count", "expected_min", "expected_max"),
    [(1667, 38, 43, 44), (1666, 38, 43, 44), (2000, 45, 44, 45)],
)
def test_grade_population_is_balanced_without_exceeding_45(
    student_count, class_count, expected_min, expected_max
):
    sizes = balanced_sizes(student_count, class_count)

    assert len(sizes) == class_count
    assert sum(sizes) == student_count
    assert min(sizes) == expected_min
    assert max(sizes) == expected_max

