import pytest

from app.api.v1.organization import UnitIn, UnitUpdateIn, validate_grade_group_binding, validate_subject_group_binding
from app.services.org.organization import validate_parent_move


def test_grade_group_requires_a_grade():
    with pytest.raises(ValueError, match="年级部必须绑定对应年级"):
        validate_grade_group_binding("grade_group", None)


def test_non_grade_group_cannot_bind_a_grade():
    with pytest.raises(ValueError, match="只有年级部可以绑定对应年级"):
        validate_grade_group_binding("department", 12)


def test_grade_group_accepts_a_grade():
    validate_grade_group_binding("grade_group", 12)


def test_subject_group_requires_an_explicit_subject():
    with pytest.raises(ValueError, match="学科组必须关联科目"):
        validate_subject_group_binding("subject_group", None)


def test_non_subject_group_cannot_bind_a_subject():
    with pytest.raises(ValueError, match="只有学科组可以关联科目"):
        validate_subject_group_binding("department", 12)


def test_subject_group_accepts_an_explicit_subject():
    validate_subject_group_binding("subject_group", 12)


def test_organization_unit_cohort_labels_are_saved_as_a_plain_year():
    assert UnitIn(name="2026届高一年级部", cohort_label="2026届").cohort_label == "2026"
    assert UnitUpdateIn(cohort_label="2026届").cohort_label == "2026"


def test_parent_move_rejects_a_descendant_to_prevent_cycles():
    rows = [
        {"id": 1, "parent_id": None},
        {"id": 2, "parent_id": 1},
        {"id": 3, "parent_id": 2},
    ]
    with pytest.raises(ValueError, match="下级组织"):
        validate_parent_move(1, 3, rows)


def test_parent_move_accepts_an_unrelated_branch():
    rows = [{"id": 1, "parent_id": None}, {"id": 2, "parent_id": None}]
    validate_parent_move(1, 2, rows)
