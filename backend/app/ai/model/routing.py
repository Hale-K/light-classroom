"""模型服务商选择与故障转移的通用状态。"""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.resilience import ProviderCircuitBreaker
from app.ai.runs.progress import Progress, report_progress
from app.ai.runs.events import TraceCallback

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass
class ProviderRoute:
    """一次 Agent 回合的服务商路由状态，供不同业务 Agent 复用。"""

    endpoints: list[ChatEndpoint]
    total_budget_seconds: int
    clock: Callable[[], float] = time.monotonic
    started_at: float = field(init=False)
    trail: list[str] = field(default_factory=list)
    last_error: ChatError | None = None

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def remaining_seconds(self) -> float:
        return self.total_budget_seconds - (self.clock() - self.started_at)

    def is_available(self, endpoint: ChatEndpoint, circuits: ProviderCircuitBreaker) -> bool:
        if circuits.is_available(endpoint.key):
            return True
        self.trail.append(f"{endpoint.name}隔离期跳过")
        return False

    def can_start(self) -> bool:
        return self.remaining_seconds() >= 30


@dataclass
class ProviderRouteResult(Generic[T]):
    """一次模型路由的结果；业务 Agent 决定最终文案或本地降级。"""

    value: T | None = None
    endpoint: ChatEndpoint | None = None
    last_error: ChatError | None = None
    trail: list[str] = field(default_factory=list)
    budget_exhausted: bool = False
    used_backup: bool = False
    spent_seconds: float = 0


class ModelProviderRouter:
    """统一处理服务商顺序、熔断隔离、故障转移和本轮时间预算。"""

    def __init__(self, circuits: ProviderCircuitBreaker):
        self._circuits = circuits

    async def route(
        self,
        endpoints: list[ChatEndpoint],
        *,
        total_budget_seconds: int,
        invoke: Callable[[ChatEndpoint], Awaitable[T]],
        on_progress: Progress | None = None,
        on_trace: TraceCallback | None = None,
        message_id: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> ProviderRouteResult[T]:
        state = ProviderRoute(endpoints, total_budget_seconds, clock=clock)
        result: ProviderRouteResult[T] = ProviderRouteResult()
        for index, endpoint in enumerate(endpoints):
            if not state.is_available(endpoint, self._circuits):
                if on_trace:
                    await on_trace("provider.skipped", {"provider": endpoint.name, "reason": "circuit_isolated"})
                logger.warning("assistant.provider isolated id=%s provider=%s", message_id or "-", endpoint.name)
                await report_progress(on_progress, "isolated", f"{endpoint.name} 正在隔离期，已跳过该服务")
                continue
            if not state.can_start():
                result.budget_exhausted = True
                break
            try:
                value = await invoke(endpoint)
            except ChatError as exc:
                if on_trace:
                    await on_trace("provider.failed", {"provider": endpoint.name, "error_class": exc.error_class, "message": exc.message})
                state.last_error = exc
                result.last_error = exc
                state.trail.append(f"{endpoint.name}({exc.error_class})")
                circuit_state = self._circuits.record_failure(endpoint.key, exc.error_class)
                logger.warning(
                    "assistant.provider fail id=%s provider=%s class=%s failures=%s isolated=%s",
                    message_id or "-", endpoint.name, exc.error_class, circuit_state.failures, circuit_state.isolated,
                )
                if circuit_state.isolated:
                    await report_progress(on_progress, "isolated", f"{endpoint.name} 连续异常，已临时隔离")
                if index < len(endpoints) - 1:
                    await report_progress(on_progress, "recovering", "当前模型未响应，正在切换备用模型继续处理")
                continue
            self._circuits.record_success(endpoint.key)
            if on_trace:
                await on_trace("provider.selected", {"provider": endpoint.name, "used_backup": index > 0})
            result.value = value
            result.endpoint = endpoint
            result.used_backup = index > 0
            result.trail = state.trail
            result.spent_seconds = total_budget_seconds - state.remaining_seconds()
            return result
        result.trail = state.trail
        result.spent_seconds = total_budget_seconds - state.remaining_seconds()
        return result
