import pytest
from pydantic import ValidationError

from app.api.v1.facilities import CampusIn
from app.api.v1.org import ClassIn, GradeIn, GradeUpdateIn
from app.services.org.seed_utils import balanced_sizes


def test_campus_accepts_planned_student_capacity():
    campus = CampusIn(name="崇仁一中", student_capacity=5000)

    assert campus.student_capacity == 5000


def test_grade_can_be_scoped_to_a_campus():
    grade = GradeIn(name="高一年级", level=1, campus_id=7)

    assert grade.campus_id == 7


def test_grade_campus_can_be_added_or_cleared_later():
    assert GradeUpdateIn(campus_id=7).model_dump(exclude_unset=True) == {"campus_id": 7}
    assert GradeUpdateIn(campus_id=None).model_dump(exclude_unset=True) == {"campus_id": None}


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


def test_planned_class_size_uses_actual_room_capacity_instead_of_45():
    administrative_class = ClassIn(
        grade_id=3,
        name="高一（1）班",
        campus_id=7,
        home_room_id=21,
        planned_student_count=57,
    )

    assert administrative_class.planned_student_count == 57


def test_planned_class_size_rejects_an_unreasonable_capacity():
    with pytest.raises(ValidationError):
        ClassIn(
            grade_id=3,
            name="高一（1）班",
            campus_id=7,
            home_room_id=21,
            planned_student_count=5001,
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
