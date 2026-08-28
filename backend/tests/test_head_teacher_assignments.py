import pytest

from app.services.head_teacher_assignments import summarize_head_teacher_assignment


def test_head_teacher_can_be_preassigned_before_teaching_relationship_exists():
    assignments = [
        {"teacher_id": 7, "class_id": 2, "subject_id": 1},
        {"teacher_id": 7, "class_id": 3, "subject_id": 1},
    ]

    assert summarize_head_teacher_assignment(7, 1, assignments) == {
        "subject_id": None,
        "taught_class_count": 2,
        "teaches_own_class": False,
    }


def test_head_teacher_summary_uses_actual_subject_and_counts_distinct_classes():
    assignments = [
        {"teacher_id": 7, "class_id": 1, "subject_id": 4},
        {"teacher_id": 7, "class_id": 2, "subject_id": 4},
        {"teacher_id": 7, "class_id": 3, "subject_id": 4},
        {"teacher_id": 8, "class_id": 4, "subject_id": 1},
    ]

    assert summarize_head_teacher_assignment(7, 1, assignments) == {
        "subject_id": 4,
        "taught_class_count": 3,
        "teaches_own_class": True,
    }
