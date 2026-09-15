from unittest.mock import AsyncMock

import pytest

from app.ai.gateway import ModelGateway, ToolGateway
from app.ai.model.chat import ChatEndpoint, ChatOutcome
from app.ai.resilience import ProviderCircuitBreaker


@pytest.mark.asyncio
async def test_model_gateway_owns_discovery_text_and_tool_calls():
    endpoint = ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 5)
    resolver = AsyncMock(return_value=[endpoint])
    text_caller = AsyncMock(return_value="回答")
    tool_caller = AsyncMock(return_value=ChatOutcome(text="工具回答"))
    gateway = ModelGateway(
        ProviderCircuitBreaker(),
        resolver=resolver,
        text_caller=text_caller,
        tool_caller=tool_caller,
    )

    assert await gateway.resolve(None, 1) == [endpoint]
    assert await gateway.complete(model="test") == "回答"
    assert (await gateway.complete_tools(model="test")).text == "工具回答"
    resolver.assert_awaited_once_with(None, 1)
    text_caller.assert_awaited_once_with(model="test")
    tool_caller.assert_awaited_once_with(model="test")


@pytest.mark.asyncio
async def test_tool_gateway_denies_tools_outside_turn_authority_and_audits():
    traces = []

    async def trace(kind, data):
        traces.append((kind, data))

    scope = ToolGateway().open_scope(
        session=None,
        tenant_id=1,
        user_id=2,
        can_manage_rules=False,
        page_context={},
        on_trace=trace,
    )

    assert "propose_rules" not in {item["function"]["name"] for item in scope.definitions}
    assert await scope.execute("propose_rules", "{}") == "工具未被授权，已拒绝执行。"
    assert traces == [("tool.denied", {"tool": "propose_rules", "reason": "not_allowed"})]


def test_tool_gateway_exposes_proposal_only_inside_privileged_scope():
    scope = ToolGateway().open_scope(
        session=None,
        tenant_id=1,
        user_id=2,
        can_manage_rules=True,
        page_context={},
    )

    assert "propose_rules" in {item["function"]["name"] for item in scope.definitions}
