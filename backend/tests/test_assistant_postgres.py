"""Opt-in PostgreSQL transaction test; creates and drops only a unique test schema."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from app.ai import actions
from app.ai.actions.models import AiAction
from app.core.config import settings
from app.models.org import Subject, TenantConfig
from app.models.audit import AuditLog
from app.services.scheduling.rules import RuleGroupDocument, dump_stored_rule_groups


@pytest.mark.skipif(os.getenv("ASSISTANT_POSTGRES_TEST") != "1", reason="opt-in isolated local PostgreSQL test")
@pytest.mark.asyncio
async def test_concurrent_confirmation_writes_once(monkeypatch):
    from app.api.v1 import scheduling
    assert make_url(settings.database_url).host in {"localhost", "127.0.0.1"}
    schema = "test_assistant_" + uuid4().hex
    admin = create_async_engine(settings.database_url)
    engine = create_async_engine(settings.database_url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def term(*args):
        return "2026", "1"
    async def grid(*args):
        return {"configured": True, "daily_periods": [7] * 5 + [0, 0]}
    from app.ai.tools import school
    monkeypatch.setattr(school, "_term", term)
    monkeypatch.setattr(scheduling, "_load_grid_config", grid)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            tables = [t.__table__ for t in (AiAction, Subject, TenantConfig, AuditLog)]
            await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
        group = RuleGroupDocument(id="g", name="测试规则组", academic_year="2026", term="1")
        async with sessions() as session:
            session.add_all([
                Subject(id=42, tenant_id=1, name="数学"),
                TenantConfig(tenant_id=1, config_key=scheduling.SCHEDULING_RULE_GROUP_CONFIG_KEY, config_value={"2026:1": dump_stored_rule_groups([group], "g")}),
            ])
            await session.commit()
            proposal = actions.RulesProposal(group_name="测试规则组", rules=[actions.RuleRequest(
                code="slot_forbidden", target_names=["数学"], priority="hard", weekdays=[3], periods=[6, 7],
            )])
            action = await actions.propose_rules(session, 1, 2, proposal)
            await session.commit()
            action_id = action.id
        async def confirm():
            async with sessions() as session:
                return await actions.decide_action(session, 1, 2, action_id, "confirm")
        first, second = await asyncio.gather(confirm(), confirm())
        assert first == second
        assert first["result"]["count"] == 1
        async with sessions() as session:
            row = (await session.execute(select(TenantConfig))).scalar_one()
            assert len(row.config_value["2026:1"]["groups"][0]["rules"]) == 1
            assert len((await session.execute(select(AuditLog))).scalars().all()) == 1
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.skipif(os.getenv("ASSISTANT_POSTGRES_TEST") != "1", reason="opt-in isolated local PostgreSQL test")
@pytest.mark.asyncio
async def test_background_run_persists_progress_and_does_not_complete_after_cancel(monkeypatch):
    from app.ai.runs.models import AiRun
    from app.ai.runs import create_run, execute_run, get_run
    from app.ai.agent import teacher
    from app.api import deps
    from app.models.org import User
    assert make_url(settings.database_url).host in {"localhost", "127.0.0.1"}
    schema = "test_assistant_" + uuid4().hex
    admin = create_async_engine(settings.database_url)
    engine = create_async_engine(settings.database_url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    async def permissions(*args):
        return []
    async def answer(*args, on_progress=None, **kwargs):
        await on_progress('tool', '正在核对课时与任教')
        entered.set()
        await release.wait()
        return teacher.TeacherTurn(text='测试查询结果')
    monkeypatch.setattr(deps, 'get_user_permission_codes', permissions)
    monkeypatch.setattr(teacher, 'handle_teacher_turn', answer)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=[AiRun.__table__, User.__table__]))
        async with sessions() as session:
            session.add(User(id=2, tenant_id=1, phone='fixture', name='测试教师', password_hash='unused', status='active', role='teacher'))
            await session.commit()
        payload = {'messages': [{'role': 'user', 'content': '检查排课'}]}
        for cancel in (False, True):
            entered.clear(); release.clear()
            rid = uuid4().hex
            async with sessions() as session:
                await create_run(session, rid, 1, 2, payload)
            task = asyncio.create_task(execute_run(rid, 1, 2, payload, sessions=sessions))
            await asyncio.wait_for(entered.wait(), 5)
            async with sessions() as session:
                progress = await get_run(session, rid, 1, 2, cancel=cancel)
                assert progress['phase'] == 'tool'
                assert progress['events'][-1]['message'] == '正在核对课时与任教'
            release.set()
            await asyncio.wait_for(task, 5)
            async with sessions() as session:
                final = await get_run(session, rid, 1, 2)
            assert final['status'] == ('cancelled' if cancel else 'done')
            assert final['result'] is None if cancel else final['result']['text'] == '测试查询结果'
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

