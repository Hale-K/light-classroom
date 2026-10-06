"""Copy historical school semester grids into independent grade plans, once."""
from datetime import datetime

from sqlalchemy import select

from app.models.org import Grade, Subject, TenantConfig
from app.models.scheduling_grid import SchedulingGridDay, SchedulingGridPlan, SchedulingGridSubject


def migrate_legacy_grids(connection) -> dict:
    from app.api.v1.scheduling import SchedulingGridConfigIn
    created = 0
    skipped = []
    rows = connection.execute(select(TenantConfig.__table__).where(TenantConfig.config_key == "scheduling_grid_config")).mappings().all()
    for row in rows:
        grades = connection.execute(select(Grade.id).where(Grade.tenant_id == row["tenant_id"])).scalars().all()
        subject_ids = set(connection.execute(select(Subject.id).where((Subject.tenant_id == row["tenant_id"]) | Subject.tenant_id.is_(None))).scalars().all())
        for scope, saved in (row["config_value"] or {}).items():
            if not isinstance(saved, dict) or ':' not in scope:
                continue
            year, term = scope.rsplit(':', 1)
            if term not in ('1', '2'):
                continue
            try:
                value = SchedulingGridConfigIn.model_validate({**saved, "academic_year": year, "term": term}).model_dump(mode="python")
            except ValueError:
                skipped.append(f"{row['tenant_id']}:{scope}")
                continue
            for grade_id in grades:
                scope_filter = (SchedulingGridPlan.tenant_id == row["tenant_id"], SchedulingGridPlan.grade_id == grade_id,
                                SchedulingGridPlan.academic_year == year, SchedulingGridPlan.term == term)
                if connection.execute(select(SchedulingGridPlan.id).where(*scope_filter)).first():
                    continue
                plan_id = connection.execute(SchedulingGridPlan.__table__.insert().values(
                    tenant_id=row["tenant_id"], grade_id=grade_id, academic_year=year, term=term,
                    first_week_parity=value["first_week_parity"].value, term_start_monday=value["term_start_monday"],
                    evening_start_period=value["evening_start_period"], created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                ).returning(SchedulingGridPlan.id)).scalar_one()
                for day in range(7):
                    connection.execute(SchedulingGridDay.__table__.insert().values(plan_id=plan_id, weekday=day + 1,
                        daytime_periods=value["daily_periods"][day], evening_odd=value["evening_daily_periods_odd"][day],
                        evening_even=value["evening_daily_periods_even"][day]))
                for parity in ('odd', 'even'):
                    for sid in sorted(set(value[f"evening_subject_ids_{parity}"]) & subject_ids):
                        connection.execute(SchedulingGridSubject.__table__.insert().values(plan_id=plan_id, parity=parity, weekday=0, subject_id=sid))
                    for day, sid in enumerate(value[f"evening_subject_ids_{parity}_by_day"], start=1):
                        if sid in subject_ids:
                            connection.execute(SchedulingGridSubject.__table__.insert().values(plan_id=plan_id, parity=parity, weekday=day, subject_id=sid))
                created += 1
    return {"created": created, "skipped": skipped}
