import pytest

from app.services.academic.student_import import context_from_config, normalize_gender


def test_student_import_uses_configured_current_context():
    context = context_from_config({
        "current_entry_year": 2026,
        "current_academic_year": "2026-2027",
        "current_term": "2",
    })
    assert context.entry_year == 2026
    assert context.academic_year == "2026-2027"
    assert context.term == "2"
    assert context.cohort_label == "2026"


def test_student_import_rejects_missing_current_context():
    with pytest.raises(ValueError, match="系统设置"):
        context_from_config({})


def test_student_import_normalizes_gender():
    assert normalize_gender("男") == "male"
    assert normalize_gender("female") == "female"
    assert normalize_gender("未知") is None
