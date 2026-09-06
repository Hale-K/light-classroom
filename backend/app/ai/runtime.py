"""轻量 Assistant Runtime：稳定服务入口与运行事件出口。

它借鉴 Cordis 的 service seam，但保持 FastAPI 代码可直接测试、按需组合。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.guide import AssistantUiGuide
from app.ai.model.routing import ModelProviderRouter
from app.ai.resilience import ProviderCircuitBreaker, provider_circuits
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress, report_progress


class ServiceRegistry:
    """能力的稳定命名入口；业务 Agent 不依赖具体构造位置。"""

    def __init__(self):
        self._services: dict[str, Any] = {}

    def register(self, name: str, service: Any) -> None:
        if name in self._services:
            raise ValueError(f"服务已注册：{name}")
        self._services[name] = service

    def get(self, name: str) -> Any:
        try:
            return self._services[name]
        except KeyError as exc:
            raise LookupError(f"未注册服务：{name}") from exc

    def has(self, name: str) -> bool:
        return name in self._services


@dataclass
class AssistantRuntime:
    """一次 Turn 的能力组合，可由不同业务 Agent 按配置替换。"""

    on_progress: Progress | None = None
    on_trace: TraceCallback | None = None
    circuits: ProviderCircuitBreaker = field(default_factory=lambda: provider_circuits)
    services: ServiceRegistry = field(default_factory=ServiceRegistry)

    def __post_init__(self) -> None:
        # 调用方可预先注册同名服务，以替换默认实现（例如测试、灰度或备用实现）。
        if not self.services.has("model_router"):
            self.services.register("model_router", ModelProviderRouter(self.circuits))
        if not self.services.has("ui_guide"):
            self.services.register("ui_guide", AssistantUiGuide)

    def service(self, name: str) -> Any:
        return self.services.get(name)

    async def progress(self, phase: str, message: str) -> None:
        await report_progress(self.on_progress, phase, message)

    async def emit(self, kind: str, data: dict[str, Any]) -> None:
        if self.on_trace:
            await self.on_trace(kind, data)
