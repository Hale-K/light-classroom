"""走班教学班任教必须计入教师档案：选科走班模式下只有 TeachingClass/TeachingClassSchedule 的教师不再显示 0。"""
import asyncio

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.deps import get_current_tenant, get_current_user
from app.api.v1.teacher_profiles import router
from app.db.session import get_session
from app.models.gaokao import TeachingClass, TeachingClassSchedule
from app.models.org import (
    Class, CourseHourPlan, OrganizationUnit, Schedule, StaffAppointment,
    Subject, TeachingAssignment, TenantConfig, User,
)


def test_walk_only_teacher_counts_teaching_class_load_and_schedule():
    engine = create_engine("sqlite://")
    models = [Class, CourseHourPlan, OrganizationUnit, Schedule, StaffAppointment,
              Subject, TeachingAssignment, TenantConfig, User,
              TeachingClass, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
    with Session(engine) as session:
        session.add_all([
            TenantConfig(tenant_id=7, config_key="academic_years", config_value={
                "current_year": "2026-2027", "current_term": "1",
            }),
            User(id=1, tenant_id=7, name="生物老师", phone="test", password_hash="unused"),
            Subject(id=2, name="生物"),
            # 走班教学班：每周 3 节，已排 2 节（TeachingClassSchedule，不走 Schedule 表）
            TeachingClass(id=11, tenant_id=7, grade_id=1, subject_id=2, name="高一生物 A 班",
                          academic_year="2026-2027", term="1", weekly_periods=3, teacher_id=1),
            TeachingClassSchedule(tenant_id=7, teaching_class_id=11, teacher_id=1, subject_id=2,
                                  academic_year="2026-2027", term="1", weekday=1, period=2),
            TeachingClassSchedule(tenant_id=7, teaching_class_id=11, teacher_id=1, subject_id=2,
                                  academic_year="2026-2027", term="1", weekday=3, period=2),
        ])
        session.commit()

        class AsyncSessionAdapter:
            async def execute(self, statement):
                return session.execute(statement)

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_session] = lambda: AsyncSessionAdapter()
        app.dependency_overrides[get_current_tenant] = lambda: 7
        app.dependency_overrides[get_current_user] = lambda: object()

        async def verify():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://test") as client:
                response = await client.get("/teacher-profiles")
                assert response.status_code == 200, response.text
                row = response.json()["data"]["items"][0]
                assert row["total_weekly_periods"] == 3
                assert row["scheduled_lessons_count"] == 2
                assert row["schedule_ratio"] > 0
                classes = row["teaching_classes"]
                assert len(classes) == 1
                assert classes[0]["kind"] == "walk"
                assert classes[0]["class_name"] == "高一生物 A 班"
                assert classes[0]["subject_name"] == "生物"
                assert classes[0]["weekly_periods"] == 3

                weekly = await client.get("/teacher-profiles/1/weekly-schedule")
                assert weekly.status_code == 200, weekly.text
                items = weekly.json()["data"]["items"]
                assert len(items) == 2
                assert all(item["kind"] == "walk" for item in items)
                assert all(item["class_name"] == "高一生物 A 班" for item in items)
                assert [(item["weekday"], item["period"]) for item in items] == [(1, 2), (3, 2)]

        asyncio.run(verify())
    engine.dispose()
