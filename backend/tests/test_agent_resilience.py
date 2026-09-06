from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_all_enabled_chat_providers_form_an_ordered_failover_chain():
    from app.ai.model.chat import resolve_chat_endpoints

    rows = [
        SimpleNamespace(id=1, name="主模型", base_url="http://primary", api_key="a", chat_model="p", timeout_seconds=20),
        SimpleNamespace(id=2, name="备用模型", base_url="http://backup", api_key="b", chat_model="b", timeout_seconds=30),
    ]

    class Result:
        def scalars(self):
            return self

        def all(self):
            return rows

    class Session:
        async def execute(self, statement):
            return Result()

    endpoints = await resolve_chat_endpoints(Session(), 7)

    assert [item.name for item in endpoints[:2]] == ["主模型", "备用模型"]
    assert endpoints[0].key == "7:1"


def test_provider_circuit_isolates_repeated_failure_and_recovers_after_cooldown():
    from app.ai.resilience import ProviderCircuitBreaker

    breaker = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=60)

    assert breaker.is_available("p1", now=100) is True
    assert breaker.record_failure("p1", "unavailable", now=101).isolated is False
    assert breaker.record_failure("p1", "unavailable", now=102).isolated is True
    assert breaker.is_available("p1", now=120) is False
    assert breaker.is_available("p1", now=163) is True
    breaker.record_success("p1")
    assert breaker.snapshot("p1").failures == 0


def test_default_provider_circuit_uses_application_configuration():
    from app.ai.resilience import provider_circuits
    from app.core.config import settings

    assert provider_circuits.failure_threshold == settings.assistant_provider_failure_threshold
    assert provider_circuits.cooldown_seconds == settings.assistant_provider_cooldown_seconds


def test_request_shaped_errors_do_not_isolate_provider():
    """超长/坏请求/空回答是对话或参数问题，不能把服务商隔离掉。"""
    from app.ai.resilience import ProviderCircuitBreaker

    breaker = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    breaker.record_failure("p", "context_overflow", now=1)
    breaker.record_failure("p", "bad_request", now=2)
    breaker.record_failure("p", "empty", now=3)
    assert breaker.is_available("p", now=4) is True
    assert breaker.snapshot("p").failures == 0

    breaker.record_failure("p", "network", now=5)
    breaker.record_failure("p", "network", now=6)
    assert breaker.is_available("p", now=7) is False
    assert breaker.is_available("p", now=67) is True


@pytest.mark.asyncio
async def test_failover_stops_starting_endpoints_once_budget_is_exhausted(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint, ChatError

    teacher.provider_circuits.clear()
    endpoints = [
        ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5),
        ChatEndpoint("1:2", "备用模型", "http://backup", "", "b", 5),
    ]
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=endpoints))
    clock = {"t": 0.0}

    def fake_monotonic():
        return clock["t"]

    async def failing_agent(*args, **kwargs):
        clock["t"] += 160  # 该 endpoint 消耗掉大部分本轮预算
        raise ChatError("无法连接", "network")

    monkeypatch.setattr(teacher.time, "monotonic", fake_monotonic)
    agent = AsyncMock(side_effect=failing_agent)
    monkeypatch.setattr(teacher, "agent_reply", agent)

    with pytest.raises(ChatError) as ei:
        await teacher.handle_teacher_turn(
            None, 1,
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}, {"role": "user", "content": "查准备度"}],
        )

    assert ei.value.error_class == "timeout"
    assert agent.await_count == 1, "预算耗尽后不得再起新 endpoint，整轮被总闸报废"


@pytest.mark.asyncio
async def test_request_shaped_failure_on_last_provider_raises_precise_error(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint, ChatError

    teacher.provider_circuits.clear()
    endpoint = ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5)
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=[endpoint]))
    monkeypatch.setattr(
        teacher, "agent_reply",
        AsyncMock(side_effect=ChatError("模型多轮调用未能完成回答，请重试或把要求拆成几条。", "exhausted")),
    )

    with pytest.raises(ChatError) as ei:
        await teacher.handle_teacher_turn(
            None, 1,
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}, {"role": "user", "content": "查准备度"}],
        )

    assert "未能完成回答" in ei.value.message, "服务还活着，不能换成『服务不可用』的本地文案"


@pytest.mark.asyncio
async def test_missing_provider_config_raises_instead_of_local_mode(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatError

    teacher.provider_circuits.clear()
    monkeypatch.setattr(
        teacher, "resolve_chat_endpoints",
        AsyncMock(side_effect=ChatError("请先在「服务商管理」启用一条带对话模型的服务商", "config")),
    )

    with pytest.raises(ChatError) as ei:
        await teacher.handle_teacher_turn(
            None, 1,
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}, {"role": "user", "content": "你好呀"}],
        )

    assert "服务商管理" in ei.value.message, "配置指引必须到达管理员"


@pytest.mark.asyncio
async def test_teacher_agent_switches_to_backup_provider_and_reports_recovery(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint, ChatError

    teacher.provider_circuits.clear()
    endpoints = [
        ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5),
        ChatEndpoint("1:2", "备用模型", "http://backup", "", "b", 5),
    ]
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=endpoints))
    agent = AsyncMock(side_effect=[
        ChatError("模型服务暂时不可用", "unavailable"),
        teacher.TeacherTurn(text="备用模型已回答"),
    ])
    monkeypatch.setattr(teacher, "agent_reply", agent)
    events = []

    async def progress(phase, message):
        events.append((phase, message))

    result = await teacher.handle_teacher_turn(
        None,
        1,
        [{"role": "user", "content": "帮我检查排课设置"}],
        on_progress=progress,
    )

    assert result.text == "备用模型已回答"
    assert len(agent.await_args_list) == 2
    assert any(phase == "recovering" for phase, _ in events)
    assert any("备用模型" in note for note in result.think)


@pytest.mark.asyncio
async def test_backup_provider_precedes_text_only_degradation(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint, ChatError

    teacher.provider_circuits.clear()
    endpoints = [
        ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5),
        ChatEndpoint("1:2", "备用模型", "http://backup", "", "b", 5),
    ]
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=endpoints))
    agent = AsyncMock(side_effect=[
        ChatError("不支持工具", "bad_request"),
        teacher.TeacherTurn(text="备用模型完成了工具查询"),
    ])
    text_fallback = AsyncMock(return_value="不应调用")
    monkeypatch.setattr(teacher, "agent_reply", agent)
    monkeypatch.setattr(teacher, "complete_chat", text_fallback)
    monkeypatch.setattr(teacher, "retrieve_skill", AsyncMock(return_value=""))

    result = await teacher.handle_teacher_turn(
        None,
        1,
        [{"role": "user", "content": "查询本校排课规则"}],
    )

    assert result.text == "备用模型完成了工具查询"
    assert agent.await_count == 2
    assert text_fallback.await_count == 0


@pytest.mark.asyncio
async def test_teacher_agent_uses_local_guide_when_all_providers_fail(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint, ChatError

    teacher.provider_circuits.clear()
    endpoint = ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5)
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=[endpoint]))
    monkeypatch.setattr(
        teacher,
        "agent_reply",
        AsyncMock(side_effect=ChatError("无法连接", "network")),
    )
    events = []

    async def progress(phase, message):
        events.append((phase, message))

    result = await teacher.handle_teacher_turn(
        None,
        1,
        [{"role": "user", "content": "排课下一步怎么做"}],
        page_path="/scheduling?tab=hours",
        on_progress=progress,
    )

    assert "本地说明模式" in result.text
    assert "未执行任何写入" in result.text
    assert any(phase == "degraded" for phase, _ in events)


@pytest.mark.asyncio
async def test_isolated_provider_is_skipped_without_calling_it(monkeypatch):
    from app.ai.agent import teacher
    from app.ai.model.chat import ChatEndpoint

    teacher.provider_circuits.clear()
    primary = ChatEndpoint("1:1", "主模型", "http://primary", "", "p", 5)
    backup = ChatEndpoint("1:2", "备用模型", "http://backup", "", "b", 5)
    teacher.provider_circuits.record_failure(primary.key, "auth")
    monkeypatch.setattr(
        teacher,
        "resolve_chat_endpoints",
        AsyncMock(return_value=[primary, backup]),
    )
    agent = AsyncMock(return_value=teacher.TeacherTurn(text="备用模型已回答"))
    monkeypatch.setattr(teacher, "agent_reply", agent)
    events = []

    async def progress(phase, message):
        events.append((phase, message))

    result = await teacher.handle_teacher_turn(
        None,
        1,
        [{"role": "user", "content": "查询教师任教"}],
        on_progress=progress,
    )

    assert result.text == "备用模型已回答"
    assert agent.await_count == 1
    assert agent.await_args.kwargs["model"] == "b"
    assert any(phase == "isolated" for phase, _ in events)
