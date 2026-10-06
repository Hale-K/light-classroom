from app.api.deps import resolve_choice_view_access


def test_director_can_view_all_student_choices():
    assert resolve_choice_view_access("director", set()) == "management"


def test_academic_director_staff_role_can_view_all_student_choices():
    assert resolve_choice_view_access("teacher", {"academic_director"}) == "management"


def test_head_teacher_can_view_only_their_class_choices():
    assert resolve_choice_view_access("teacher", {"head_teacher"}) == "head_teacher"


def test_regular_teacher_cannot_view_grade_wide_student_choices():
    assert resolve_choice_view_access("teacher", set()) is None
