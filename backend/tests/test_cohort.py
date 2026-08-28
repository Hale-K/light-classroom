from app.services.cohort import expected_cohort_label, normalize_cohort_label


def test_expected_cohort_label_uses_entry_year_semantics():
    assert expected_cohort_label("2026-2027", 1) == "2026"
    assert expected_cohort_label("2026-2027", 2) == "2025"
    assert expected_cohort_label("2026-2027", 3) == "2024"


def test_normalize_cohort_label_accepts_display_suffix():
    assert normalize_cohort_label("2026届") == "2026"
