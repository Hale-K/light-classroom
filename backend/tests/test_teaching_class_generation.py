import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.gaokao import (GenerateTeachingClassesIn, GenerateWalkScheduleIn,
                              _shared_teaching_rooms, generate_teaching_classes, generate_schedules)
from app.models.facility import Building, ResourceAllocationRule, Room, RoomCohortAllocation
from app.models.gaokao import (GaokaoScheme, StudentSubjectChoice, TeachingClass,
                              TeachingClassSchedule, TeachingClassStudent, TeachingSubjectHourPlan)
from app.models.org import Grade, Subject, TenantConfig
from app.services.academic.gaokao import form_teaching_classes


class Adapter:
    def __init__(self, db): self.db = db
    async def get(self, model, key): return self.db.get(model, key)
    async def execute(self, statement): return self.db.execute(statement)
    def add(self, item): self.db.add(item)
    def add_all(self, items): self.db.add_all(items)
    async def flush(self): self.db.flush()
    async def commit(self): self.db.commit()


def test_balanced_subject_classes_keep_all_students_and_capacity():
    groups = form_teaching_classes([{"student_id": i, "subject_ids": [28]} for i in range(1, 243)], capacity=40)
    sizes = [len(g.student_ids) for g in groups]
    assert sizes == [35, 35, 35, 35, 34, 34, 34]
    assert {i for g in groups for i in g.student_ids} == set(range(1, 243))


def test_preview_without_rooms_then_confirm_and_guard_replacement():
    engine = create_engine("sqlite://")
    models = [Grade, Subject, GaokaoScheme, StudentSubjectChoice, TeachingSubjectHourPlan,
              TeachingClass, TeachingClassStudent, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine) as db:
        db.add(Grade(id=1, tenant_id=7, name="高一", level=1))
        db.add_all([Subject(id=i, tenant_id=7, name=name) for i, name in [(1, "物理"), (2, "化学"), (3, "生物")]])
        db.add(GaokaoScheme(id=1, tenant_id=7, name="312", entry_year=2026, primary_subject_ids=[1], secondary_subject_ids=[2, 3]))
        db.add_all([StudentSubjectChoice(tenant_id=7, student_id=i, scheme_id=1, academic_year="2026-2027",
                    effective_term="2", primary_subject_id=1, secondary_subject_ids=[2, 3]) for i in range(1, 43)])
        db.add_all([TeachingSubjectHourPlan(tenant_id=7, grade_id=1, subject_id=i, academic_year="2026-2027", term="2", weekly_periods=4) for i in [2, 3]])
        db.add(TeachingClass(id=100, tenant_id=7, grade_id=1, subject_id=2, sequence=1, name="历史学期班", academic_year="2026-2027", term="1"))
        db.commit()

        async def verify():
            scope = dict(grade_id=1, academic_year="2026-2027", term="2", capacity=40)
            deps = dict(session=Adapter(db), user=object(), tenant_id=7)
            with patch("app.api.v1.gaokao._grade_student_ids", new=AsyncMock(return_value=list(range(1, 43)))), patch("app.api.v1.gaokao._shared_teaching_rooms", new=AsyncMock(return_value=[])):
                preview = (await generate_teaching_classes(GenerateTeachingClassesIn(**scope, preview=True), **deps))["data"]
                assert preview["created"] == 4 and preview["available_room_count"] == 0
                assert all(c["student_count"] == 21 and c["weekly_periods"] == 4 for c in preview["classes"])
                assert len(db.execute(select(TeachingClass)).scalars().all()) == 1
                with pytest.raises(HTTPException) as no_preview:
                    await generate_teaching_classes(GenerateTeachingClassesIn(**scope), **deps)
                assert no_preview.value.status_code == 409
                result = await generate_teaching_classes(GenerateTeachingClassesIn(**scope, preview_token=preview["preview_token"]), **deps)
                assert result["data"]["created"] == 4
                assert result["data"]["memberships"] == 0
                assert db.execute(select(TeachingClassStudent)).scalars().all() == []
                current = db.execute(select(TeachingClass).where(TeachingClass.term == "2")).scalars().all()
                current[0].teacher_id = 9
                current[0].room = "保留教室"
                db.add(TeachingClassSchedule(tenant_id=7, teaching_class_id=current[0].id, subject_id=2, academic_year="2026-2027", term="2", weekday=1, period=1))
                db.commit()
                second = (await generate_teaching_classes(GenerateTeachingClassesIn(**scope, preview=True), **deps))["data"]
                assert second["existing_class_count"] == 4
                with pytest.raises(HTTPException) as unconfirmed:
                    await generate_teaching_classes(GenerateTeachingClassesIn(**scope, preview_token=second["preview_token"]), **deps)
                assert unconfirmed.value.status_code == 409
                assert db.get(TeachingClass, current[0].id).teacher_id == 9
                with pytest.raises(HTTPException) as stale:
                    await generate_teaching_classes(GenerateTeachingClassesIn(**scope, replace_existing=True, preview_token=preview["preview_token"]), **deps)
                assert stale.value.status_code == 409
                await generate_teaching_classes(GenerateTeachingClassesIn(**scope, replace_existing=True, preview_token=second["preview_token"]), **deps)
                assert db.get(TeachingClass, 100).term == "1"
                assert not db.execute(select(TeachingClassSchedule)).scalars().all()
        asyncio.run(verify())
    engine.dispose()


def test_shared_rooms_only_use_matching_active_semester_cohort_and_campus():
    engine = create_engine("sqlite://")
    models = [Grade, Building, Room, ResourceAllocationRule, RoomCohortAllocation, TenantConfig]
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine) as db:
        grade = Grade(id=1, tenant_id=7, name="高一", level=1, campus_id=1)
        db.add(grade)
        db.add_all([Building(id=i, tenant_id=7, campus_id=i, name=f"楼{i}") for i in [1, 2]])
        for i, term, cohort, tenant, campus, mode, status in [
            (1, "2", "2026届", 7, 1, "shared", "active"), (2, "1", "2026", 7, 1, "shared", "active"),
            (3, "2", "2025", 7, 1, "shared", "active"), (4, "2", "2026", 8, 1, "shared", "active"),
            (5, "2", "2026", 7, 2, "shared", "active"), (6, "2", "2026", 7, 1, "exclusive", "active"),
            (7, "2", "2026", 7, 1, "shared", "released"),
        ]:
            db.add(Room(id=i, tenant_id=tenant, building_id=campus, name=f"教室{i}", floor=1, capacity=50))
            db.add(ResourceAllocationRule(id=i, tenant_id=tenant, name="规则", campus_id=campus, cohort_label=cohort, academic_year="2026-2027", term=term, allocation_mode=mode, status=status))
            db.add(RoomCohortAllocation(tenant_id=tenant, rule_id=i, room_id=i, cohort_label=cohort, academic_year="2026-2027", term=term, allocation_mode=mode, status=status))
        db.add(TenantConfig(tenant_id=7, config_key="walkspace:1:2026-2027", config_value={"shared_room_ids": [2, 3, 4, 5, 6, 7]}))
        db.commit()
        rooms = asyncio.run(_shared_teaching_rooms(Adapter(db), 7, grade, "2026-2027", "2"))
        assert [r.id for r in rooms] == [1]
    engine.dispose()


def test_schedule_can_use_one_selected_room_without_using_the_whole_pool():
    engine = create_engine("sqlite://")
    models = [Grade, Room, TeachingClass, TeachingClassStudent, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine) as db:
        db.add(Grade(id=1, tenant_id=7, name="高二", level=2))
        db.add_all([Room(id=i, tenant_id=7, building_id=1, name=f"教室{i}", floor=1, capacity=50) for i in range(1, 8)])
        db.add(TeachingClass(id=1, tenant_id=7, grade_id=1, subject_id=2, name="化学01", academic_year="2026-2027", term="2", weekly_periods=4))
        db.add(TeachingClassStudent(tenant_id=7, teaching_class_id=1, student_id=1))
        db.commit()

        async def verify():
            scope = dict(grade_id=1, academic_year="2026-2027", term="2")
            deps = dict(session=Adapter(db), user=object(), tenant_id=7)
            rooms = list(db.execute(select(Room)).scalars().all())
            with patch("app.api.v1.gaokao._shared_teaching_rooms", new=AsyncMock(return_value=rooms)):
                for selected in [[], [99]]:
                    with pytest.raises(HTTPException) as invalid:
                        await generate_schedules(GenerateWalkScheduleIn(**scope, room_ids=selected), **deps)
                    assert invalid.value.status_code == 422
                result = await generate_schedules(GenerateWalkScheduleIn(**scope, room_ids=[3]), **deps)
                assert result["data"]["created"] == 4 and result["data"]["unplaced"] == []
                assert {s.room for s in db.execute(select(TeachingClassSchedule)).scalars()} == {"楼栋1 · 教室3"}
        asyncio.run(verify())
    engine.dispose()
