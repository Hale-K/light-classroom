"""Absolute cycle deadlines and call-level recovery preserve completed work."""
import asyncio
import json
import time

import pytest

from app.ai.gateway.model import ModelGateway
from app.ai.graph.loop import ReactLoop
from app.ai.model.chat import ChatEndpoint, ChatError, ChatOutcome, ToolCallOut
from app.ai.resilience import ProviderCircuitBreaker
from app.ai.runs.service import RUN_TIMEOUT, execution_view


TOOLS = [{"type": "function", "function": {"name": "lookup_rules"}}]


def make_loop(caller, executor, **kwargs):
    return ReactLoop(base_url="http://primary", api_key="", model="p", timeout=1,
                     messages=[{"role": "user", "content": "核对规则"}],
                     tools=TOOLS, caller=caller, executor=executor, **kwargs)


@pytest.mark.asyncio
async def test_complete_cycle_budget_includes_model_and_tool_and_collects_cancelled_work():
    stopped = asyncio.Event()

    async def caller(**kwargs):
        await asyncio.sleep(.025)
        return ChatOutcome(tool_calls=[ToolCallOut("1", "lookup_rules", "{}")])

    async def executor(*args):
        try:
            await asyncio.sleep(1)
        finally:
            stopped.set()

    started = time.monotonic()
    with pytest.raises(ChatError) as caught:
        await make_loop(caller, executor, cycle_timeout_seconds=.05).run()
    assert caught.value.error_class == "timeout"
    assert "循环" in caught.value.message
    assert stopped.is_set()
    assert time.monotonic() - started < .3


@pytest.mark.asyncio
async def test_answer_repair_shares_cycle_budget():
    calls = 0
    stopped = asyncio.Event()

    async def caller(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(.02)
            return ChatOutcome(text="Let me think about it. " * 30)
        try:
            await asyncio.sleep(1)
        finally:
            stopped.set()

    async def executor(*args):
        raise AssertionError("No query was requested")

    with pytest.raises(ChatError, match="循环"):
        await make_loop(caller, executor, cycle_timeout_seconds=.04).run()
    assert calls == 2
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_whole_task_budget_spans_multiple_cycles():
    stopped = asyncio.Event()
    calls = 0

    async def caller(**kwargs):
        nonlocal calls
        calls += 1
        try:
            await asyncio.sleep(.025)
        finally:
            if calls >= 2:
                stopped.set()
        return ChatOutcome(tool_calls=[ToolCallOut(str(calls), "lookup_rules", "{}")])

    async def executor(*args):
        return "已查到规则"

    with pytest.raises(ChatError, match="任务"):
        await make_loop(caller, executor, max_steps=10,
                        cycle_timeout_seconds=.5, turn_timeout_seconds=.04).run()
    assert stopped.is_set()
    assert calls == 2


@pytest.mark.asyncio
async def test_explicit_cancel_propagates_and_collects_model_call():
    entered, stopped = asyncio.Event(), asyncio.Event()

    async def caller(**kwargs):
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    async def executor(*args):
        return "unused"

    task = asyncio.create_task(make_loop(caller, executor).run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_provider_failover_keeps_evidence_without_replaying_tools():
    endpoints = [ChatEndpoint("p", "首选", "http://primary", "", "p", 1),
                 ChatEndpoint("b", "备用", "http://backup", "", "b", 1)]
    requests, queries, events = [], [], []

    async def caller(**request):
        requests.append(request)
        tool_messages = [item for item in request["messages"] if item.get("role") == "tool"]
        if not tool_messages:
            return ChatOutcome(tool_calls=[ToolCallOut("q", "lookup_rules", "{}")])
        if request["model"] == "p":
            raise ChatError("暂时无法连接", "network")
        assert tool_messages[-1]["content"] == "已查询：每班周五有七个必排课位"
        return ChatOutcome(text="已核对周五七个必排课位。")

    gateway = ModelGateway(ProviderCircuitBreaker(), tool_caller=caller)

    async def routed(**request):
        return await gateway.complete_tools_routed(endpoints=endpoints, on_trace=trace, **request)

    async def executor(name, arguments):
        queries.append(name)
        return "已查询：每班周五有七个必排课位"

    async def trace(kind, data):
        events.append((kind, data))

    outcome = await make_loop(routed, executor).run()
    assert "七个" in outcome.text
    assert queries == ["lookup_rules"]
    assert [item["model"] for item in requests] == ["p", "p", "b"]
    assert any(kind == "provider.selected" and data["used_backup"] for kind, data in events)


@pytest.mark.asyncio
async def test_provider_call_deadline_includes_retries_and_collects_cancelled_call():
    stopped = asyncio.Event()

    async def caller(**request):
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    gateway = ModelGateway(ProviderCircuitBreaker(), tool_caller=caller)
    endpoint = ChatEndpoint("p", "首选", "http://primary", "", "p", 10)
    with pytest.raises(ChatError) as caught:
        await gateway.complete_tools_routed(endpoints=[endpoint], timeout=.03, messages=[])
    assert caught.value.error_class == "timeout"
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_structured_plan_updates_are_traced_and_projected_safely():
    plan = {"goal": "比较三个方案", "steps": [
        {"id": "capacity", "label": "核对课位", "status": "completed", "summary": "已查35至45节"},
        {"id": "compare", "label": "对比方案", "status": "running", "summary": ""}]}
    replies = [ChatOutcome(tool_calls=[ToolCallOut("p", "plan_task", "{}")]),
               ChatOutcome(text="方案已核对。")]
    events = []

    async def caller(**request):
        return replies.pop(0)

    async def executor(*args):
        return json.dumps({"ok": True, "data": {"plan": plan}}, ensure_ascii=False)

    async def trace(kind, data):
        events.append({"type": f"assistant.{kind}", "data": data})

    loop = make_loop(caller, executor, on_trace=trace)
    loop.tools = [{"type": "function", "function": {"name": "plan_task"}}]
    await loop.run()
    assert any(event["type"] == "assistant.planning.updated" for event in events)
    view = execution_view([{"type": "assistant.harness.selected", "data": {"name": "planning"}}, *events], status="done")
    assert view["mode"] == "planning"
    assert view["tasks"][0]["status"] == "completed"
    assert "messages" not in json.dumps(view)


def test_production_limits_match_ten_minute_task_two_minute_cycles():
    assert RUN_TIMEOUT == 600
    assert ReactLoop.__dataclass_fields__["cycle_timeout_seconds"].default == 120
    assert ReactLoop.__dataclass_fields__["turn_timeout_seconds"].default == 600


def test_durable_plan_survives_trace_rollover():
    plan = {'goal': '核对三个方案', 'steps': [{'id': 'verify', 'label': '核对方案',
                                           'status': 'running', 'summary': ''}]}
    view = execution_view([], status='running', plan=plan)
    assert view['mode'] == 'planning'
    assert view['tasks'][0]['id'] == 'verify'
    assert view['goal'] == '核对三个方案'


@pytest.mark.asyncio
@pytest.mark.parametrize('tool_name', ['lookup_planning_basis', 'validate_hour_scenarios', 'plan_task', 'update_plan_task'])
async def test_planning_tool_json_preserves_complete_evidence(tool_name):
    evidence = json.dumps({'ok': True, 'data': {'detail': '科目课时' * 1200,
                          'fixed_subjects': {'体育': 2}, 'all_scenarios_valid': True}}, ensure_ascii=False)
    calls = 0

    async def caller(**request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ChatOutcome(tool_calls=[ToolCallOut('1', tool_name, '{}')])
        observed = json.loads(request['messages'][-1]['content'])
        assert observed['data']['fixed_subjects']['体育'] == 2
        assert observed['data']['all_scenarios_valid'] is True
        return ChatOutcome(text='证据已完整取得。')

    async def executor(*args):
        return evidence

    loop = make_loop(caller, executor)
    loop.tools = [{'type': 'function', 'function': {'name': tool_name}}]
    assert '完整' in (await loop.run()).text


@pytest.mark.asyncio
async def test_recovered_provider_is_preferred_on_next_cycle_in_same_task():
    from types import SimpleNamespace
    from app.ai.agent.agent_loop import run_agent_loop
    from app.ai.harness.router import QUERY_HARNESS

    endpoints = [ChatEndpoint('p', '首选', 'http://primary', '', 'p', 5),
                 ChatEndpoint('b', '备用', 'http://backup', '', 'b', 5)]
    models, queries = [], []

    async def caller(**request):
        models.append(request['model'])
        if request['model'] == 'p':
            raise ChatError('首选服务离线', 'network')
        if not any(item.get('role') == 'tool' for item in request['messages']):
            return ChatOutcome(tool_calls=[ToolCallOut('q', 'lookup_rules', '{}')])
        return ChatOutcome(text='规则查询已完成。')

    async def executor(*args):
        queries.append('rules')
        return '有一个规则组'

    gateway = ModelGateway(ProviderCircuitBreaker(), tool_caller=caller)
    outcome = await run_agent_loop([{'role': 'user', 'content': '查询规则'}], '',
        base_url='http://primary', api_key='', model='p', timeout=5,
        on_progress=None, on_trace=None, on_step=None,
        model_gateway=gateway, tool_scope=SimpleNamespace(definitions=TOOLS, execute=executor, plan=None),
        harness=QUERY_HARNESS, page_title=None, page_path=None, can=None, cannot=None,
        page_context=None, retrieved='', provider_endpoints=endpoints)
    assert outcome.text == '规则查询已完成。'
    assert models == ['p', 'b', 'b']
    assert queries == ['rules']


@pytest.mark.asyncio
@pytest.mark.parametrize('formatted', [False, True])
async def test_unfinished_plan_cannot_stop_early_and_corrects_in_next_cycle(formatted):
    completed = False
    requests = []

    async def caller(**request):
        requests.append(request)
        if len(requests) == 1:
            if formatted:
                return ChatOutcome(tool_calls=[ToolCallOut('f', 'format_markdown', '{}')])
            return ChatOutcome(text='三个方案全部完成。')
        if len(requests) == 2:
            assert request['messages'][-1]['role'] == 'system'
            assert '任务仍未校验' in request['messages'][-1]['content']
            return ChatOutcome(tool_calls=[ToolCallOut('v', 'lookup_rules', '{}')])
        return ChatOutcome(text='三个方案已据证据校验。')

    async def executor(name, arguments):
        nonlocal completed
        if name == 'format_markdown':
            return json.dumps({'ok': True, 'data': {'markdown': '三个方案全部完成。'}})
        completed = True
        return '已完成取证和方案校验'

    async def guard(text):
        return None if completed else '任务仍未校验，请先取证完成计划。'

    loop = make_loop(caller, executor, final_guard=guard)
    loop.tools = [*TOOLS, {'type': 'function', 'function': {'name': 'format_markdown'}}]
    assert '据证据' in (await loop.run()).text
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_final_cycle_cannot_deliver_unverified_complete_claim():
    async def caller(**request):
        return ChatOutcome(text='方案全部完成。')

    async def executor(*args):
        raise AssertionError('No tools requested')

    async def guard(text):
        return '任务计划中还有未校验方案。'

    with pytest.raises(ChatError) as caught:
        await make_loop(caller, executor, max_steps=1, final_guard=guard).run()
    assert caught.value.error_class == 'invalid_answer'


@pytest.mark.asyncio
@pytest.mark.parametrize('slow_cleanup', [False, True])
async def test_job_deadline_cancels_initial_identity_query_and_bounds_status_cleanup(monkeypatch, slow_cleanup):
    from types import SimpleNamespace
    from app.ai.runs import service

    query_stopped, cleanup_stopped = asyncio.Event(), asyncio.Event()
    terminal_values = []

    class SlowDatabase:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            if statement.is_select:
                try:
                    await asyncio.sleep(10)
                finally:
                    query_stopped.set()
            terminal_values.append(statement.compile().params)
            if slow_cleanup:
                try:
                    await asyncio.sleep(10)
                finally:
                    cleanup_stopped.set()
            return SimpleNamespace(rowcount=1)

        async def commit(self):
            return None

    monkeypatch.setattr(service, 'RUN_TIMEOUT', .025)
    monkeypatch.setattr(service, 'TERMINAL_PERSIST_TIMEOUT', .025)
    started = time.monotonic()
    await service.execute_run('a' * 32, 1, 1, {'messages': []}, sessions=SlowDatabase)
    assert query_stopped.is_set(), 'Even identity lookup before model execution must be cancelled'
    assert terminal_values[0]['status'] == 'timed_out'
    assert time.monotonic() - started < .3
    if slow_cleanup:
        assert cleanup_stopped.is_set(), 'Unavailable DB must not leave terminal cleanup hanging'
