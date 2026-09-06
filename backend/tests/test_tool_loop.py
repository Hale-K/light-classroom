"""工具循环：模型给 tool_calls 就执行喂回，末步强制收口成文本。"""
import asyncio

import pytest

from app.ai.graph.loop import run_tool_loop
from app.ai.model.chat import ChatError, ChatOutcome, ToolCallOut

_TOOLS = [{"type": "function", "function": {"name": "lookup_teachers", "parameters": {}}}]


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

        outcome = await run_tool_loop(
            base_url="http://x", api_key="k", model="m", timeout=10,
            messages=[{"role": "user", "content": "查课"}],
            tools=_TOOLS, executor=executor, caller=caller,
        )
        return outcome, seen

    outcome, seen = asyncio.run(main())
    assert outcome.text == "周一第5节是空堂"
    assert outcome.steps == []
    assert seen[0]["tools"] == _TOOLS


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

        outcome = await run_tool_loop(
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

        outcome = await run_tool_loop(
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

        outcome = await run_tool_loop(
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

        outcome = await run_tool_loop(
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

        outcome = await run_tool_loop(
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
            await run_tool_loop(
                base_url="http://x", api_key="k", model="m", timeout=10,
                messages=[{"role": "user", "content": "规则"}],
                tools=_TOOLS, executor=executor, caller=caller, max_steps=1,
            )
        return ei

    ei = asyncio.run(main())
    assert ei.value.error_class == "empty"
