"""Relational storage for grade time structures."""
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.scheduling_grid import SchedulingGridDay, SchedulingGridPlan, SchedulingGridSubject, SchedulingGridSlot


async def load_grade_grid(session: AsyncSession, tenant_id: int, grade_id: int, year: str, term: str) -> dict:
    plan = (await session.execute(select(SchedulingGridPlan).where(
        SchedulingGridPlan.tenant_id == tenant_id, SchedulingGridPlan.grade_id == grade_id,
        SchedulingGridPlan.academic_year == year, SchedulingGridPlan.term == term,
    ))).scalar_one_or_none()
    if plan is None:
        return {}
    days = (await session.execute(select(SchedulingGridDay).where(SchedulingGridDay.plan_id == plan.id))).scalars().all()
    result = {"daily_periods": [0] * 7, "evening_daily_periods_odd": [0] * 7, "evening_daily_periods_even": [0] * 7,
              "evening_start_period": plan.evening_start_period, "first_week_parity": plan.first_week_parity,
              "term_start_monday": plan.term_start_monday,
              "evening_subject_ids_odd": [], "evening_subject_ids_even": [],
              "evening_subject_ids_odd_by_day": [None] * 7, "evening_subject_ids_even_by_day": [None] * 7, "slot_overrides": []}
    for day in days:
        result["daily_periods"][day.weekday - 1] = day.daytime_periods
        result["evening_daily_periods_odd"][day.weekday - 1] = day.evening_odd
        result["evening_daily_periods_even"][day.weekday - 1] = day.evening_even
    subjects = (await session.execute(select(SchedulingGridSubject).where(SchedulingGridSubject.plan_id == plan.id))).scalars().all()
    for item in subjects:
        if item.weekday:
            result[f"evening_subject_ids_{item.parity}_by_day"][item.weekday - 1] = item.subject_id
        else:
            result[f"evening_subject_ids_{item.parity}"].append(item.subject_id)
    slots = (await session.execute(select(SchedulingGridSlot).where(SchedulingGridSlot.plan_id == plan.id).order_by(SchedulingGridSlot.weekday, SchedulingGridSlot.period, SchedulingGridSlot.week_parity))).scalars().all()
    result["slot_overrides"] = [{"weekday": slot.weekday, "period": slot.period, "week_parity": slot.week_parity, "slot_type": slot.slot_type} for slot in slots]
    return result


async def save_grade_grid(session: AsyncSession, tenant_id: int, grade_id: int, year: str, term: str, value: dict) -> None:
    plan = (await session.execute(select(SchedulingGridPlan).where(
        SchedulingGridPlan.tenant_id == tenant_id, SchedulingGridPlan.grade_id == grade_id,
        SchedulingGridPlan.academic_year == year, SchedulingGridPlan.term == term,
    ).with_for_update())).scalar_one_or_none()
    if plan is None:
        plan = SchedulingGridPlan(tenant_id=tenant_id, grade_id=grade_id, academic_year=year, term=term)
        session.add(plan)
        await session.flush()
    plan.first_week_parity = getattr(value["first_week_parity"], "value", value["first_week_parity"])
    plan.term_start_monday = value.get("term_start_monday")
    plan.evening_start_period = value.get("evening_start_period")
    await session.execute(delete(SchedulingGridDay).where(SchedulingGridDay.plan_id == plan.id))
    await session.execute(delete(SchedulingGridSubject).where(SchedulingGridSubject.plan_id == plan.id))
    await session.execute(delete(SchedulingGridSlot).where(SchedulingGridSlot.plan_id == plan.id))
    for slot in value.get("slot_overrides", []):
        session.add(SchedulingGridSlot(plan_id=plan.id, **slot))
    for day in range(7):
        session.add(SchedulingGridDay(plan_id=plan.id, weekday=day + 1, daytime_periods=value["daily_periods"][day],
            evening_odd=value["evening_daily_periods_odd"][day], evening_even=value["evening_daily_periods_even"][day]))
    for parity in ("odd", "even"):
        for subject_id in sorted(set(value[f"evening_subject_ids_{parity}"])):
            session.add(SchedulingGridSubject(plan_id=plan.id, parity=parity, subject_id=subject_id))
        for day, subject_id in enumerate(value[f"evening_subject_ids_{parity}_by_day"], start=1):
            if subject_id is not None:
                session.add(SchedulingGridSubject(plan_id=plan.id, parity=parity, weekday=day, subject_id=subject_id))
