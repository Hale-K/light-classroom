"""工具循环：模型给 tool_calls 就执行喂回，末步强制收口成文本。"""
import asyncio
import json

import pytest

from app.ai.graph.loop import ReactLoop
from app.ai.model.chat import ChatError, ChatOutcome, ToolCallOut

_TOOLS = [{"type": "function", "function": {"name": "lookup_teachers", "parameters": {}}}]


def test_paged_evidence_preserves_complete_json_for_model():
    seen = []
    payload = json.dumps({'data': {'items': ['课程明细' * 200] * 10,
                                  'has_more': True, 'next_offset': 10}})

    async def executor(name, arguments):
        return payload

    caller = _caller_factory([
        ChatOutcome(tool_calls=[ToolCallOut(id='evidence', name='lookup_timetable', arguments='{}')]),
        ChatOutcome(text='已查询，另有下一页。'),
    ], seen)
    asyncio.run(ReactLoop(base_url='http://x', api_key='k', model='m', timeout=10,
                         messages=[], tools=[{'type': 'function', 'function': {
                             'name': 'lookup_timetable', 'parameters': {}}}],
                         executor=executor, caller=caller).run())
    result = next(m for m in seen[1]['messages'] if m['role'] == 'tool')
    assert json.loads(result['content']) == json.loads(payload)


def _caller_factory(responses: list[ChatOutcome], seen: list[dict]):
    async def caller(**kwargs):
        seen.append(kwargs)
        return responses.pop(0)

    return caller


def test_loop_answers_directly_without_tools():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([ChatOutcome(text="周一第5节是空堂")], seen)

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "查课"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "周一第5节是空堂"
    assert outcome.steps == []
    assert seen[0]["tools"] == _TOOLS


def test_steer_arriving_during_model_call_wakes_next_step():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([
            ChatOutcome(text="原方向的临时回答"),
            ChatOutcome(text="已按新方向回答"),
        ], seen)
        inbox_calls = 0

        async def on_step(_step):
            nonlocal inbox_calls
            inbox_calls += 1
            if inbox_calls == 2:
                return [{"role": "user", "content": "执行方向调整：只看高一", "_wake": True}]
            return []

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "检查全校"}],
            tools=_TOOLS, executor=executor, caller=caller, on_step=on_step,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "已按新方向回答"
    assert len(seen) == 2
    assert seen[1]["messages"][-1] == {"role": "user", "content": "执行方向调整：只看高一"}


def test_inject_arriving_during_model_call_does_not_wake_next_step():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([ChatOutcome(text="已完成")], seen)
        inbox_calls = 0

        async def on_step(_step):
            nonlocal inbox_calls
            inbox_calls += 1
            if inbox_calls == 2:
                return [{"role": "system", "content": "页签发生变化", "_wake": False}]
            return []

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "检查全校"}],
            tools=_TOOLS, executor=executor, caller=caller, on_step=on_step,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "已完成"
    assert len(seen) == 1


def test_loop_executes_tool_and_feeds_result_back():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory(
            [
                ChatOutcome(
                    tool_calls=[ToolCallOut(id="call_1", name="lookup_teachers", arguments='{"subject":"数学"}')]
                ),
                ChatOutcome(text="数学老师共 3 人"),
            ],
            seen,
        )

        async def executor(name, arguments):
            assert name == "lookup_teachers"
            assert '"数学"' in arguments
            return "2026学年第1学期，任教「数学」的在职教师共 3 人：\n- 张三：数学"

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "数学老师有谁"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "数学老师共 3 人"
    assert [s.tool for s in outcome.steps] == ["lookup_teachers"]
    assert "任教「数学」" in outcome.steps[0].detail
    # 第二轮对话里应出现 assistant 的 tool_calls 与 tool 结果
    convo = seen[1]["messages"]
    assert convo[1]["role"] == "assistant"
    assert convo[1]["tool_calls"][0]["function"]["name"] == "lookup_teachers"
    assert convo[2] == {"role": "tool", "tool_call_id": "call_1", "content": "2026学年第1学期，任教「数学」的在职教师共 3 人：\n- 张三：数学"}


def test_loop_emits_replayable_model_and_tool_events():
    async def main():
        trace = []

        async def caller(**kwargs):
            if not trace:
                raise AssertionError("模型请求必须先记入轨迹")
            if len([event for event in trace if event[0] == "model.request"]) == 1:
                return ChatOutcome(tool_calls=[ToolCallOut(id="call_1", name="lookup_teachers", arguments="{}")])
            return ChatOutcome(text="已完成")

        async def executor(name, arguments):
            return "教师共 3 人"

        async def record(kind, data):
            trace.append((kind, data))

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "教师有谁"}], tools=_TOOLS,
            executor=executor, caller=caller, on_trace=record,
        )
        return outcome, trace

    outcome, trace = asyncio.run(main())
    assert outcome.text == "已完成"
    assert [kind for kind, _ in trace] == [
        "model.request", "model.response", "tool.call", "tool.result", "model.request", "model.response",
    ]
    assert trace[0][1]["messages"] == [{"role": "user", "content": "教师有谁"}]
    assert trace[3][1]["content"] == "教师共 3 人"


def test_loop_forces_text_on_last_step():
    async def main():
        seen: list[dict] = []

        async def caller(**kwargs):
            seen.append(kwargs)
            if len(seen) == 1:
                return ChatOutcome(tool_calls=[ToolCallOut(id="c", name="lookup_rules", arguments="{}")])
            return ChatOutcome(text="已有 2 个规则组")

        async def executor(name, arguments):
            return "规则组 2 个"

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "规则"}],
            tools=_TOOLS, executor=executor, caller=caller, max_steps=2,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "已有 2 个规则组"
    assert seen[-1]["tools"] is None, "最后一步必须收走工具表，强制模型给文本"


def test_loop_converts_executor_error_into_tool_result():
    async def main():
        seen: list[dict] = []

        async def caller(**kwargs):
            seen.append(kwargs)
            if len(seen) == 1:
                return ChatOutcome(tool_calls=[ToolCallOut(id="c", name="lookup_teachers", arguments="bad json")])
            return ChatOutcome(text="查不到该教师")

        async def executor(name, arguments):
            raise RuntimeError("db down")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "王老师是谁"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    tool_msg = seen[1]["messages"][2]
    assert tool_msg["role"] == "tool"
    assert "执行失败" in tool_msg["content"]
    assert outcome.text == "查不到该教师"


def test_final_step_hallucinated_tool_calls_are_dropped():
    """收口轮已撤工具表，个别服务商仍返回 tool_calls：丢弃调用只收文本。"""

    async def main():
        seen: list[dict] = []

        async def caller(**kwargs):
            seen.append(kwargs)
            if len(seen) == 1:
                return ChatOutcome(tool_calls=[ToolCallOut(id="c", name="lookup_rules", arguments="{}")])
            return ChatOutcome(text="只剩文本回答", tool_calls=[ToolCallOut(id="d", name="lookup_rules", arguments="{}")])

        async def executor(name, arguments):
            raise AssertionError("收口轮不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "规则"}],
            tools=_TOOLS, executor=executor, caller=caller, max_steps=2,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "只剩文本回答"
    assert len(seen) == 2


def test_final_step_hallucinated_calls_with_empty_text_raise_empty():
    async def main():
        async def caller(**kwargs):
            return ChatOutcome(text="", tool_calls=[ToolCallOut(id="d", name="lookup_rules", arguments="{}")])

        async def executor(name, arguments):
            raise AssertionError("收口轮不应执行工具")

        with pytest.raises(ChatError) as ei:
            await run_loop(
                base_url="http://x", api_key="k", model="m", timeout=10,
                messages=[{"role": "user", "content": "规则"}],
                tools=_TOOLS, executor=executor, caller=caller, max_steps=1,
            )
        return ei

    ei = asyncio.run(main())
    assert ei.value.error_class == "empty"


def test_chinese_conversation_english_reasoning_leak_retries_once():
    """中文会话收到纯英文长文：视为推理泄漏，强制中文重答一次。"""
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([
            ChatOutcome(text="Let me understand the user's request first. They are on the slots page and want to "
                             "arrange subjects per class. I should check the current setup, then design a plan."),
            ChatOutcome(text="按每周 54 节课位：建议语文 7、数学 7、英语 7，剩余分给理科。"),
        ], seen)

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "语数外物化生政史怎么配课时？"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert "语文" in outcome.text
    assert len(seen) == 2
    assert "不要展示分析推理过程" in seen[1]["messages"][-1]["content"]


def test_normal_chinese_answer_does_not_retry():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([ChatOutcome(text="语文建议每周 7 节。")], seen)

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "语文配多少节合适？"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert "语文" in outcome.text
    assert len(seen) == 1


def test_english_query_expects_english_answer_without_retry():
    async def main():
        seen: list[dict] = []
        caller = _caller_factory([ChatOutcome(text="Sure, tell me the grade and term you want to check.")], seen)

        async def executor(name, arguments):
            raise AssertionError("不应执行工具")

        outcome = await run_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "How many classes are configured?"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text.startswith("Sure")
    assert len(seen) == 1


async def run_loop(**kwargs):
    return await ReactLoop(**kwargs).run()


@pytest.mark.asyncio
@pytest.mark.parametrize('repair', ['fails', 'still_analysis'])
async def test_mixed_language_analysis_never_returns_when_repair_fails(repair):
    leak = 'Let me understand 高一年级 and 课位结构. ' + 'I should query the setup before answering. ' * 20
    calls = 0
    async def caller(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1 or repair == 'still_analysis':
            return ChatOutcome(text=leak)
        raise ChatError('连接失败', 'network')
    async def executor(*args):
        raise AssertionError('Text about calling a tool is not an actual tool call')
    with pytest.raises(ChatError):
        await run_loop(base_url='http://x', api_key='', model='m', timeout=5,
                       messages=[{'role': 'user', 'content': '查看高一课时'}],
                       tools=_TOOLS, caller=caller, executor=executor)
    assert calls == 2
