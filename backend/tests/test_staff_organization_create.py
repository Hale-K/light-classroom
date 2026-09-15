"""本地 PostgreSQL 隔离 schema：新增账号和多组织任命同一事务提交。"""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from app.api.v1 import staff
from app.core.config import settings
from app.models.enums import BaseUserRole
from app.models.org import Grade, OrganizationUnit, StaffAppointment, Subject, User


@pytest.mark.asyncio
async def test_create_staff_assigns_multiple_organizations_atomically(monkeypatch):
    if make_url(settings.database_url).host not in {"localhost", "127.0.0.1"}:
        pytest.skip("仅在本地 PostgreSQL 隔离 schema 运行")
    schema = "test_staff_" + uuid4().hex
    admin = create_async_engine(settings.database_url)
    engine = create_async_engine(settings.database_url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def skip_roles(*args):
        return ["subject_teacher"]

    monkeypatch.setattr(staff, "replace_staff_roles", skip_roles)
    principal = User(id=9, tenant_id=1, name="管理员", phone="00000000009", password_hash="x", role=BaseUserRole.director)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            tables = [model.__table__ for model in (User, Subject, Grade, OrganizationUnit, StaffAppointment)]
            await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
        async with sessions() as session:
            session.add_all([
                OrganizationUnit(id=11, tenant_id=1, name="教务处", unit_type="department"),
                OrganizationUnit(id=12, tenant_id=1, name="数学教研组", unit_type="subject_group"),
                OrganizationUnit(id=13, tenant_id=1, name="高一部", unit_type="grade_group"),
                OrganizationUnit(id=14, tenant_id=1, name="高二部", unit_type="grade_group"),
            ])
            await session.commit()
            result = await staff.create_staff(
                staff.StaffCreateIn(name="测试教师", phone="00000000001", password="test123", roles=["subject_teacher"], unit_ids=[11, 12]),
                user=principal, tenant_id=1, session=session,
            )
            user_id = result["data"]["id"]
            appointments = (await session.execute(select(StaffAppointment).where(StaffAppointment.staff_id == user_id))).scalars().all()
            assert {item.organization_unit_id for item in appointments} == {11, 12}
            assert all(item.position_code == "member" for item in appointments)
            with pytest.raises(HTTPException, match="只能同时归属一个年级部"):
                await staff.create_staff(
                    staff.StaffCreateIn(name="无效教师", phone="00000000002", password="test123", unit_ids=[13, 14]),
                    user=principal, tenant_id=1, session=session,
                )
            users = (await session.execute(select(User))).scalars().all()
            assert len(users) == 1
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()
