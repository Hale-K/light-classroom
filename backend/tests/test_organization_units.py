import pytest

from app.api.v1.organization import UnitIn, UnitUpdateIn, validate_grade_group_binding, validate_subject_group_binding


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
