import json

import pytest

from app.ai.gateway.tool import ToolScope
from app.ai.graph.loop import ReactLoop
from app.ai.model.chat import ChatOutcome, ToolCallOut


def payload(**changes):
    return json.dumps({"summary": "已核对，仍有缺项。", "sections": [
        {"title": "核对结果", "type": "table", "columns": ["科目", "人数"],
         "rows": [["政治", "50"], ["化学", "26"]]},
        {"title": "下一步", "type": "steps", "items": ["核对任课关系", "重新预览"]},
    ], **changes}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_gateway_formats_without_accessing_school_data_in_plan_mode():
    scope = ToolScope(object(), 1, 2, False, {"assistant_mode": "plan"})
    assert "format_markdown" in {t["function"]["name"] for t in scope.definitions}
    result = json.loads(await scope.execute("format_markdown", payload()))
    assert result["ok"] is True
    assert result["data"]["markdown"] == (
        "已核对，仍有缺项。\n\n#### 核对结果\n\n| 科目 | 人数 |\n"
        "| --- | --- |\n| 政治 | 50 |\n| 化学 | 26 |\n\n"
        "#### 下一步\n\n1. 核对任课关系\n2. 重新预览")


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ["{", "[]", payload(reasoning="思考"), payload(sections=[
    {"title": "错误表格", "type": "table", "columns": ["人数", "科目"], "rows": [["50"]]},
]), payload(summary="<think>不要显示</think>")])
async def test_invalid_format_is_rejected(arguments):
    scope = ToolScope(object(), 1, None, False, None)
    result = json.loads(await scope.execute("format_markdown", arguments))
    assert result["ok"] is False
    assert result["code"] == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_formatter_escapes_html_and_table_separators():
    scope = ToolScope(object(), 1, None, False, None)
    result = json.loads(await scope.execute("format_markdown", payload(summary="<img src=x>", sections=[
        {"type": "table", "columns": ["说明"], "rows": [["A|B\n下一行"]]},
    ])))
    assert "<img" not in result["data"]["markdown"]
    assert "A\\|B 下一行" in result["data"]["markdown"]


@pytest.mark.asyncio
async def test_formatter_completes_answer_without_another_model_round():
    scope = ToolScope(object(), 1, None, False, None)
    calls = []

    async def caller(**kwargs):
        calls.append(kwargs)
        assert len(calls) == 1
        return ChatOutcome(text="", tool_calls=[ToolCallOut(id="fmt", name="format_markdown", arguments=payload())])

    outcome = await ReactLoop(base_url="http://unused", api_key="unused", model="test", timeout=10,
        messages=[{"role": "user", "content": "整理查询结果"}], tools=scope.definitions,
        executor=scope.execute, caller=caller).run()
    assert outcome.text.startswith("已核对，仍有缺项。\n\n#### 核对结果")
    assert [step.tool for step in outcome.steps] == ["format_markdown"]


@pytest.mark.asyncio
async def test_formatter_is_not_available_to_tool_free_harness():
    scope = ToolScope(object(), 1, None, False, None, allowed_tools=frozenset())
    assert scope.definitions == []
    assert "拒绝" in await scope.execute("format_markdown", payload())


@pytest.mark.asyncio
async def test_invalid_format_returns_error_to_model_for_correction():
    scope = ToolScope(object(), 1, None, False, None)
    seen = []

    async def caller(**kwargs):
        seen.append({**kwargs, "messages": list(kwargs["messages"])})
        args = "{" if len(seen) == 1 else payload()
        return ChatOutcome(text="", tool_calls=[ToolCallOut(id=str(len(seen)), name="format_markdown", arguments=args)])

    outcome = await ReactLoop(base_url="http://unused", api_key="unused", model="test", timeout=10,
        messages=[{"role": "user", "content": "整理"}], tools=scope.definitions,
        executor=scope.execute, caller=caller).run()
    assert len(seen) == 2
    assert json.loads(seen[1]["messages"][-1]["content"])["code"] == "INVALID_ARGUMENT"
    assert "#### 核对结果" in outcome.text


@pytest.mark.asyncio
async def test_parallel_query_cannot_finish_with_premature_formatted_answer():
    scope = ToolScope(object(), 1, None, False, None)
    seen = []
    executed = []

    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(text="", tool_calls=[
                ToolCallOut(id="query", name="lookup_teachers", arguments="{}"),
                ToolCallOut(id="fmt", name="format_markdown", arguments=payload()),
            ])
        return ChatOutcome(text="请先确认查询范围。")

    async def executor(name, arguments):
        executed.append(name)
        return "查询范围缺失。"

    outcome = await ReactLoop(base_url="http://unused", api_key="unused", model="test", timeout=10,
        messages=[{"role": "user", "content": "查询并整理"}], tools=scope.definitions,
        executor=executor, caller=caller).run()
    assert executed == ["lookup_teachers"]
    assert outcome.text == "请先确认查询范围。"


@pytest.mark.asyncio
async def test_user_steering_before_format_completion_is_not_lost():
    scope = ToolScope(object(), 1, None, False, None)
    seen = []
    inbox_calls = 0

    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(text="", tool_calls=[ToolCallOut(id="fmt", name="format_markdown", arguments=payload())])
        return ChatOutcome(text="已改为只列下一步。")

    async def on_step(_step):
        nonlocal inbox_calls
        inbox_calls += 1
        return [{"role": "user", "content": "只列下一步", "_wake": True}] if inbox_calls == 2 else []

    outcome = await ReactLoop(base_url="http://unused", api_key="unused", model="test", timeout=10,
        messages=[{"role": "user", "content": "整理"}], tools=scope.definitions,
        executor=scope.execute, caller=caller, on_step=on_step).run()
    assert outcome.text == "已改为只列下一步。"
    assert seen[1]["messages"][-1] == {"role": "user", "content": "只列下一步"}
