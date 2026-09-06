from app.ai.model.chat import ChatEndpoint
from app.ai.model.routing import ProviderRoute
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
