from datetime import date
import pytest
from app.services.scheduling import generate_exam_schedule
from app.services.exam_rules import ExamRules, calendar_violations
from app.services.exam_time_slots import apply_subject_time_slots


def place(preferences, *, start=date(2026, 10, 16), excluded=(), limit=4, gap=0):
    items = generate_exam_schedule([{'id': i, 'grade_id': 1, 'subject_id': i} for i in (1, 2, 3)], start_date=start)
    rules = ExamRules(subject_time_slots=preferences, student_daily_limit=limit, min_break_minutes=gap)
    result = apply_subject_time_slots(items, start_date=start, sessions=[('09:00', '11:00'), ('14:30', '16:30')], excluded_dates=set(excluded), rules=rules)
    assert not calendar_violations(result, rules)
    return result


def test_selected_afternoon_keeps_order_and_skips_weekend_and_excluded_day():
    rows = place({1: '14:30', 2: '09:00', 3: '09:00'}, excluded=[date(2026, 10, 19)])
    assert [(r.exam_date, r.start_time) for r in rows] == [(date(2026, 10, 16), '14:30'), (date(2026, 10, 20), '09:00'), (date(2026, 10, 21), '09:00')]


def test_one_exam_per_day_still_allows_selected_afternoon():
    rows = place({1: '14:30'}, start=date(2026, 10, 12), limit=1)
    assert rows[0].start_time == '14:30'
    assert len({r.exam_date for r in rows}) == 3


def test_all_automatic_is_backward_compatible():
    rows = place({})
    assert [r.start_time for r in rows] == ['09:00', '14:30', '09:00']


def test_occupied_morning_postpones_without_changing_preferred_period_or_exclusions():
    start = date(2026, 10, 11)
    items = generate_exam_schedule([{'id': 1, 'grade_id': 1, 'subject_id': 1}], start_date=start)
    rows = apply_subject_time_slots(items, start_date=start,
        sessions=[('09:00', '11:00'), ('14:30', '16:30')],
        excluded_dates={date(2026, 10, 13)}, rules=ExamRules(subject_time_slots={1: '09:00'}),
        unavailable=lambda item, day, begin, end: day == date(2026, 10, 12))
    assert [(r.exam_date, r.start_time) for r in rows] == [(date(2026, 10, 14), '09:00')]


def test_no_available_session_terminates_with_specific_reason():
    start = date(2026, 10, 12)
    items = generate_exam_schedule([{'id': 1, 'grade_id': 1, 'subject_id': 1}], start_date=start)
    with pytest.raises(ValueError, match='一年内没有满足'):
        apply_subject_time_slots(items, start_date=start, sessions=[('09:00', '11:00')],
            excluded_dates=set(), rules=ExamRules(), unavailable=lambda *args: True)


@pytest.mark.parametrize('limit', [1, 4])
def test_nine_subjects_all_in_morning_use_nine_available_days(limit):
    start = date(2026, 10, 12)
    items = generate_exam_schedule([{'id': i, 'grade_id': 1, 'subject_id': i} for i in range(1, 10)], start_date=start)
    rules = ExamRules(subject_time_slots={i: '09:00' for i in range(1, 10)}, student_daily_limit=limit)
    rows = apply_subject_time_slots(items, start_date=start, sessions=[('09:00', '11:00'), ('14:30', '16:30')], excluded_dates=set(), rules=rules)
    assert len(rows) == len({r.exam_date for r in rows}) == 9
    assert all((r.start_time, r.end_time) == ('09:00', '11:00') and r.exam_date.weekday() < 5 for r in rows)
    assert [r.subject_id for r in rows] == list(range(1, 10))
    assert not calendar_violations(rows, rules)


def test_deleted_time_slot_is_rejected_instead_of_silently_ignored():
    with pytest.raises(ValueError, match='重新选择'):
        place({1: '08:00'})


def test_plan_checker_detects_existing_plan_breaking_new_subject_time_rule():
    rows = generate_exam_schedule([{'id': 1, 'grade_id': 1, 'subject_id': 1}], start_date=date(2026, 10, 12))
    assert '14:30' in calendar_violations(rows, ExamRules(subject_time_slots={1: '14:30'}))[0]


@pytest.mark.parametrize('preferences', [{1: '25:00'}, {1: '09:60'}, {-1: '09:00'}])
def test_invalid_preferences_are_rejected(preferences):
    with pytest.raises(ValueError):
        ExamRules(subject_time_slots=preferences)
