from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.actions import RuleRequest, build_rule, check_action, fingerprint
from app.ai.actions.models import AiAction


def test_rule_requires_explicit_target_time_and_priority():
    with pytest.raises(ValidationError):
        RuleRequest(code="slot_forbidden", target_names=["数学"])
    request = RuleRequest(code="slot_forbidden", target_names=["数学"], priority="hard")
    with pytest.raises(ValueError, match="星期和节次"):
        build_rule(request, [1], {"daily_periods": [7] * 5 + [0, 0]})


def test_rule_rejects_unavailable_slots_and_unsupported_scope():
    request = RuleRequest(code="slot_forbidden", target_names=["数学"], priority="hard", weekdays=[6], periods=[2])
    with pytest.raises(ValueError, match="课位"):
        build_rule(request, [1], {"daily_periods": [7] * 5 + [0, 0]})
    with pytest.raises(ValidationError):
        RuleRequest(code="slot_fixed", target_names=["数学"], priority="hard")


def test_rule_uses_resolved_ids_and_compiles():
    from app.services.scheduling.rules import RuleGroupDocument, compile_rule_group
    request = RuleRequest(code="subject_consecutive", target_names=["数学"], priority="hard", minimum_block_length=2, minimum_days=1)
    rule = build_rule(request, [42], {"daily_periods": [7] * 5 + [0, 0]})
    assert rule.target.ids == [42]
    assert rule.params == {"minimum_block_length": 2, "minimum_days": 1}
    group = RuleGroupDocument(id="g", name="高一", academic_year="2026", term="1", rules=[rule])
    assert compile_rule_group(group)[0].status == "ready"


def test_action_scope_expiry_and_cancellation():
    action = AiAction(tenant_id=1, user_id=2, payload={}, expires_at=datetime.utcnow() + timedelta(minutes=20))
    check_action(action, 1, 2)
    for tenant, user in [(2, 2), (1, 3)]:
        with pytest.raises(HTTPException) as exc:
            check_action(action, tenant, user)
        assert exc.value.status_code == 404
    action.status = "cancelled"
    with pytest.raises(HTTPException):
        check_action(action, 1, 2)
    action.status = "pending"
    action.expires_at = datetime.utcnow() - timedelta(seconds=1)
    with pytest.raises(HTTPException) as exc:
        check_action(action, 1, 2)
    assert exc.value.status_code == 409


def test_fingerprint_detects_changed_rules_independent_of_key_order():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})


@pytest.mark.parametrize("code, fields, target", [
    ("slot_forbidden", {"weekdays": [1], "periods": [2]}, "subject"),
    ("teacher_forbidden_slots", {"weekdays": [1], "periods": [2]}, "teacher"),
    ("subject_consecutive", {"minimum_block_length": 2, "minimum_days": 1}, "subject"),
    ("teacher_daily_limit", {"max_lessons_per_day": 4}, "teacher"),
])
def test_all_supported_rules_compile(code, fields, target):
    from app.services.scheduling.rules import RuleGroupDocument, compile_rule_group
    rule = build_rule(RuleRequest(code=code, target_names=["测试对象"], priority="hard", **fields), [42], {"daily_periods": [7] * 5 + [0, 0]})
    assert rule.target.type == target
    group = RuleGroupDocument(id="g", name="测试", academic_year="2026", term="1", rules=[rule])
    assert compile_rule_group(group)[0].status == "ready"


@pytest.fixture
def database(monkeypatch):
    """Real isolated SQLite storage; only async transport and school clock/grid are adapted."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlmodel import SQLModel
    from app.ai import actions
    from app.api.v1 import scheduling
    from app.models.org import Subject, TenantConfig, User
    from app.models.audit import AuditLog
    from app.services.scheduling.rules import RuleGroupDocument, dump_stored_rule_groups

    engine = create_engine("sqlite://")
    tables = [t.__table__ for t in (AiAction, Subject, TenantConfig, User, AuditLog)]
    SQLModel.metadata.create_all(engine, tables=tables)
    sync = Session(engine, expire_on_commit=False)
    class SessionAdapter:
        add = sync.add
        async def execute(self, stmt):
            return sync.execute(stmt)
        async def flush(self):
            sync.flush()
        async def commit(self):
            sync.commit()
    async def term(*args):
        return "2026", "1"
    async def grid(*args):
        return {"configured": True, "daily_periods": [7] * 5 + [0, 0]}
    from app.ai.tools import school
    monkeypatch.setattr(school, "_term", term)
    monkeypatch.setattr(scheduling, "_load_grid_config", grid)
    group = RuleGroupDocument(id="g", name="高一规则", academic_year="2026", term="1")
    sync.add_all([
        Subject(id=42, tenant_id=1, name="数学"),
        Subject(id=43, tenant_id=2, name="外校科目"),
        TenantConfig(tenant_id=1, config_key=scheduling.SCHEDULING_RULE_GROUP_CONFIG_KEY, config_value={"2026:1": dump_stored_rule_groups([group], "g")}),
    ])
    sync.commit()
    yield SessionAdapter(), sync
    sync.close()
    engine.dispose()


async def make_proposal(session):
    from app.ai.actions import RulesProposal, propose_rules
    return await propose_rules(session, 1, 2, RulesProposal(group_name="高一规则", rules=[
        RuleRequest(code="slot_forbidden", target_names=["数学"], priority="hard", weekdays=[3], periods=[6, 7]),
    ]))


@pytest.mark.asyncio
async def test_proposal_does_not_write_rules_confirm_is_idempotent_and_audited(database):
    from sqlalchemy import select
    from app.ai.actions import decide_action
    from app.models.org import TenantConfig
    from app.models.audit import AuditLog
    session, sync = database
    action = await make_proposal(session)
    sync.commit()
    row = sync.execute(select(TenantConfig)).scalar_one()
    assert row.config_value["2026:1"]["groups"][0]["rules"] == []
    result = await decide_action(session, 1, 2, action.id, "confirm")
    again = await decide_action(session, 1, 2, action.id, "confirm")
    assert result == again
    assert result["status"] == "executed"
    assert result["result"]["verification"]["compiled"] is True
    assert len(result["result"]["verification"]["rule_ids"]) == 1
    assert len(row.config_value["2026:1"]["groups"][0]["rules"]) == 1
    assert len(sync.execute(select(AuditLog)).scalars().all()) == 1


@pytest.mark.asyncio
async def test_cancel_and_cross_tenant_confirmation_never_write(database):
    from app.ai.actions import decide_action
    session, sync = database
    action = await make_proposal(session)
    sync.commit()
    for tenant, user in [(2, 2), (1, 3)]:
        with pytest.raises(HTTPException) as error:
            await decide_action(session, tenant, user, action.id, "confirm")
        assert error.value.status_code == 404
    cancelled = await decide_action(session, 1, 2, action.id, "cancel")
    assert cancelled["status"] == "cancelled"
    assert await decide_action(session, 1, 2, action.id, "cancel") == cancelled
    with pytest.raises(HTTPException):
        await decide_action(session, 1, 2, action.id, "confirm")


@pytest.mark.asyncio
async def test_changed_group_rejects_confirmation_without_overwriting(database):
    from sqlalchemy import select
    from app.ai.actions import decide_action
    from app.models.org import TenantConfig
    session, sync = database
    action = await make_proposal(session)
    sync.commit()
    row = sync.execute(select(TenantConfig)).scalar_one()
    import copy
    config = copy.deepcopy(row.config_value)
    config["2026:1"]["groups"][0]["name"] = "另一位老师已修改"
    row.config_value = config
    sync.commit()
    with pytest.raises(HTTPException) as error:
        await decide_action(session, 1, 2, action.id, "confirm")
    assert error.value.status_code == 409
    assert row.config_value == config
    assert action.status == "pending"


@pytest.mark.asyncio
async def test_cross_school_targets_are_not_resolved(database):
    from app.ai.actions import resolve_targets
    session, _ = database
    request = RuleRequest(code="slot_forbidden", target_names=["外校科目"], priority="hard", weekdays=[1], periods=[1])
    with pytest.raises(ValueError, match="未找到"):
        await resolve_targets(session, 1, request)


@pytest.mark.asyncio
async def test_shared_subject_dictionary_survives_orm_tenant_filter(database):
    from sqlalchemy import event
    from sqlalchemy.orm import with_loader_criteria
    from app.ai.actions import resolve_targets
    from app.models.org import Subject
    session, sync = database
    sync.add(Subject(id=44, tenant_id=None, name="共享科目"))
    sync.commit()
    @event.listens_for(sync, "do_orm_execute")
    def filter_tenant(state):
        if state.is_select:
            state.statement = state.statement.options(with_loader_criteria(Subject, Subject.tenant_id == 1))
    request = RuleRequest(code="slot_forbidden", target_names=["共享科目"], priority="hard", weekdays=[1], periods=[1])
    assert await resolve_targets(session, 1, request) == [44]


@pytest.mark.asyncio
async def test_failed_commit_rolls_back_rules_and_receipt(database, monkeypatch):
    from sqlalchemy import select
    from app.ai.actions import decide_action
    from app.models.org import TenantConfig
    from app.models.audit import AuditLog
    session, sync = database
    action = await make_proposal(session)
    sync.commit()
    async def fail():
        sync.flush()
        raise RuntimeError("simulated transaction failure")
    monkeypatch.setattr(session, "commit", fail)
    with pytest.raises(RuntimeError):
        await decide_action(session, 1, 2, action.id, "confirm")
    # get_session performs this rollback when a request fails.
    sync.rollback()
    sync.expire_all()
    assert sync.get(AiAction, action.id).status == "pending"
    assert sync.execute(select(TenantConfig)).scalar_one().config_value["2026:1"]["groups"][0]["rules"] == []
    assert sync.execute(select(AuditLog)).scalars().all() == []


@pytest.mark.asyncio
async def test_chat_tool_to_confirm_endpoint_complete_flow(database, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import json
    from app.api.v1 import assistant
    from app.ai.agent import assistant_agent
    from app.ai.gateway import model as gateway_model
    from app.ai.intent import AssistantIntent, IntentDecision, IntentGateway
    from app.ai.model.chat import ChatOutcome, ToolCallOut
    session, sync = database
    monkeypatch.setattr(assistant, "get_user_permission_codes", AsyncMock(return_value={"scheduling:assign"}))
    from app.ai.model.chat import ChatEndpoint
    monkeypatch.setattr(gateway_model, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "fixture", 5)]))
    caller = AsyncMock(return_value=ChatOutcome(text="不可使用模型声称的已保存", tool_calls=[ToolCallOut(id="1", name="propose_rules", arguments=json.dumps({
        "group_name": "高一规则", "rules": [{"code": "slot_forbidden", "target_names": ["数学"], "priority": "hard", "weekdays": [3], "periods": [6, 7]}],
    }))]))
    monkeypatch.setattr(gateway_model, "complete_chat_tools", caller)
    monkeypatch.setattr(
        IntentGateway,
        "classify",
        AsyncMock(
            return_value=IntentDecision(
                AssistantIntent.CONFIGURATION, 0.91, "pgvector"
            )
        ),
    )
    user = SimpleNamespace(id=2, tenant_id=1)
    result = await assistant.assistant_chat(assistant.ChatIn(messages=[assistant.ChatTurn(role="user", content="数学周三6、7节禁排")]), session, user, 1)
    assert caller.await_count == 1  # Successful proposal stops before another model call.
    assert "不可使用模型" not in result["data"]["text"]
    plan = result["data"]["plan"]
    assert plan["status"] == "pending"
    sync.commit()
    # Permission revoked between preview and confirmation must block the write.
    monkeypatch.setattr(assistant, "get_user_permission_codes", AsyncMock(return_value=set()))
    with pytest.raises(HTTPException) as error:
        await assistant.assistant_action(plan["id"], assistant.ActionDecision(decision="confirm"), session, user, 1)
    assert error.value.status_code == 403
    monkeypatch.setattr(assistant, "get_user_permission_codes", AsyncMock(return_value={"scheduling:assign"}))
    confirmed = await assistant.assistant_action(plan["id"], assistant.ActionDecision(decision="confirm"), session, user, 1)
    assert confirmed["data"]["status"] == "executed"
    assert confirmed["data"]["result"]["count"] == 1
