from app.api.v1.teacher_profiles import _plan_equivalent_weekly
from app.models.enums import EveningParity
from app.models.org import CourseHourPlan


def _plan(**kwargs) -> CourseHourPlan:
    defaults = dict(
        tenant_id=1,
        class_id=1,
        subject_id=1,
        academic_year="2026-2027",
        term="1",
        weekday_periods=0,
        saturday_periods=0,
        weekly_periods=0,
        evening_periods_odd=0,
        evening_periods_even=0,
        evening_parity=EveningParity.all,
    )
    defaults.update(kwargs)
    return CourseHourPlan(**defaults)


def test_plan_hours_include_saturday_and_full_evening():
    plan = _plan(
        weekday_periods=5,
        saturday_periods=1,
        weekly_periods=6,
        evening_periods_odd=1,
        evening_periods_even=1,
        evening_parity=EveningParity.all,
    )
    assert _plan_equivalent_weekly(plan) == 7


def test_plan_hours_half_evening_either_counts_half():
    plan = _plan(
        weekday_periods=4,
        saturday_periods=0,
        weekly_periods=4,
        evening_periods_odd=1,
        evening_periods_even=1,
        evening_parity=EveningParity.either,
    )
    assert _plan_equivalent_weekly(plan) == 4.5


def test_plan_hours_odd_only_evening_is_half():
    plan = _plan(
        weekday_periods=3,
        saturday_periods=0.5,
        weekly_periods=3.5,
        evening_periods_odd=1,
        evening_periods_even=0,
        evening_parity=EveningParity.odd,
    )
    assert _plan_equivalent_weekly(plan) == 4.0
