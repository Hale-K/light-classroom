import pytest

from app.ai.model.chat import ChatEndpoint
from app.ai.model.chat import ChatError
from app.ai.model.routing import ModelProviderRouter, ProviderRoute
from app.ai.resilience import ProviderCircuitBreaker


def test_provider_route_skips_isolated_endpoint_and_keeps_config_order():
    primary = ChatEndpoint("1:primary", "主模型", "http://p", "", "p", 10)
    backup = ChatEndpoint("1:backup", "备用模型", "http://b", "", "b", 10)
    circuits = ProviderCircuitBreaker()
    circuits.record_failure(primary.key, "auth")

    route = ProviderRoute([primary, backup], 180)

    assert route.is_available(primary, circuits) is False
    assert route.is_available(backup, circuits) is True
    assert route.trail == ["主模型隔离期跳过"]


@pytest.mark.asyncio
async def test_provider_router_fails_over_and_reports_recovery():
    primary = ChatEndpoint("1:primary", "主模型", "http://p", "", "p", 10)
    backup = ChatEndpoint("1:backup", "备用模型", "http://b", "", "b", 10)
    circuits = ProviderCircuitBreaker()
    progress = []

    async def invoke(endpoint):
        if endpoint is primary:
            raise ChatError("暂时不可用", "network")
        return "完成"

    async def report(phase, message):
        progress.append((phase, message))

    result = await ModelProviderRouter(circuits).route(
        [primary, backup],
        total_budget_seconds=180,
        invoke=invoke,
        on_progress=report,
    )

    assert result.value == "完成"
    assert result.endpoint is backup
    assert result.used_backup is True
    assert result.trail == ["主模型(network)"]
    assert progress == [("recovering", "当前模型未响应，正在切换备用模型继续处理")]
