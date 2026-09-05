from unittest.mock import AsyncMock

import pytest

from app.ai.agent import teacher
from app.ai.model.chat import ChatOutcome, ToolCallOut


@pytest.mark.asyncio
async def test_short_followup_keeps_history_and_rules_query_uses_agent(monkeypatch):
    monkeypatch.setattr(teacher, "resolve_chat_endpoint", AsyncMock(return_value=("http://test", "", "test", 5)))
    agent = AsyncMock(return_value=teacher.TeacherTurn(text="已查询"))
    monkeypatch.setattr(teacher, "agent_reply", agent)
    for turns in [
        [{"role": "user", "content": "本校有哪些规则？"}],
        [{"role": "user", "content": "数学禁排"}, {"role": "assistant", "content": "周几？"}, {"role": "user", "content": "周三"}],
    ]:
        result = await teacher.handle_teacher_turn(None, 1, turns)
        assert result.text == "已查询"
        assert agent.call_args.args[2] == turns


@pytest.mark.asyncio
async def test_model_has_no_execute_tool_and_unprivileged_proposal_is_denied(monkeypatch):
    from app.ai.graph import loop
    seen = []
    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(tool_calls=[ToolCallOut(id="1", name="propose_rules", arguments="{}")])
        return ChatOutcome(text="无配置权限")
    monkeypatch.setattr(loop, "complete_chat_tools", caller)
    result = await teacher.agent_reply(None, 1, [{"role": "user", "content": "添加规则"}], base_url="http://test", api_key="", model="test", timeout=5)
    assert result.plan is None
    assert all("execute" not in t["function"]["name"] and t["function"]["name"] != "propose_rules" for t in seen[0]["tools"])
    assert "没有排课配置权限" in seen[1]["messages"][-1]["content"]
