"""Historical lessons must never fill an empty current term."""
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


def test_empty_current_term_does_not_fall_back_to_historical_classes_or_lessons():
    engine = create_engine("sqlite://")
    models = [Class, CourseHourPlan, OrganizationUnit, Schedule, StaffAppointment,
              Subject, TeachingAssignment, TenantConfig, User,
              TeachingClass, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
    with Session(engine) as session:
        session.add_all([
            TenantConfig(tenant_id=7, config_key="academic_years", config_value={
                "current_year": "2026-2027", "current_term": "2",
            }),
            User(id=1, tenant_id=7, name="教师", phone="test", password_hash="unused"),
            Subject(id=1, name="体育"),
            Class(id=1, tenant_id=7, grade_id=1, name="高一（1）班",
                  academic_year="2026-2027", term="1", head_teacher_id=1),
            Schedule(tenant_id=7, class_id=1, teacher_id=1, subject_id=1,
                     weekday=2, period=3, academic_year="2026-2027", term="1"),
            TeachingAssignment(tenant_id=7, class_id=1, teacher_id=1, subject_id=1,
                               academic_year="2026-2027", term="1", weekly_periods=2),
            CourseHourPlan(tenant_id=7, class_id=1, subject_id=1,
                           academic_year="2026-2027", term="1", weekly_periods=2),
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
                for params in ({}, {"academic_year": "2026-2027", "term": "2"}):
                    response = await client.get("/teacher-profiles", params=params)
                    assert response.status_code == 200, response.text
                    data = response.json()["data"]
                    assert data["defaults"]["term"] == "2"
                    assert data["class_summary"]["class_count"] == 0
                    assert data["class_summary"]["weekly_target"] == 0
                    assert data["class_summary"]["scheduled_lessons"] == 0
                    assert not data["items"][0]["is_head_teacher"]
                    assert data["items"][0]["teaching_classes"] == []
                    weekly = await client.get("/teacher-profiles/1/weekly-schedule", params=params)
                    assert weekly.status_code == 200, weekly.text
                    assert weekly.json()["data"]["items"] == []
                    assert weekly.json()["data"]["applied"]["term"] == "2"

                historical = await client.get("/teacher-profiles/1/weekly-schedule",
                                               params={"academic_year": "2026-2027", "term": "1"})
                assert historical.status_code == 200, historical.text
                assert len(historical.json()["data"]["items"]) == 1
                previous_year = await client.get("/teacher-profiles/1/weekly-schedule",
                                                 params={"academic_year": "2025-2026", "term": "1"})
                assert previous_year.json()["data"]["items"] == []

        asyncio.run(verify())
    engine.dispose()
