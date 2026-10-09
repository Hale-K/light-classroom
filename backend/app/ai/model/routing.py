"""模型服务商选择与故障转移的通用状态。"""
from __future__ import annotations

import logging
import time
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.resilience import ProviderCircuitBreaker
from app.ai.runs.progress import Progress, report_progress
from app.ai.runs.events import TraceCallback

logger = logging.getLogger(__name__)
T = TypeVar("T")

_ERROR_PRIORITY = {
    # 用户真正需要处理的配置、额度或请求问题必须保留，不能被后续备用通道的
    # 一次连接失败覆盖；超时也比离线备用模型更能解释本轮为何失败。
    "auth": 5, "quota": 5, "config": 5,
    "bad_request": 4, "context_overflow": 4, "parse": 4, "empty": 4,
    "incomplete_output": 4, "invalid_answer": 4, "exhausted": 4,
    "timeout": 3, "rate_limit": 3,
    "unavailable": 2, "network": 1, "unknown": 0,
}


def _prefer_error(current: ChatError | None, candidate: ChatError) -> ChatError:
    if current is None:
        return candidate
    return candidate if _ERROR_PRIORITY.get(candidate.error_class, 0) >= _ERROR_PRIORITY.get(current.error_class, 0) else current


def _failover_message(error_class: str) -> str:
    reason = {
        "timeout": "首选模型本次调用超时",
        "network": "当前模型连接失败",
        "incomplete_output": "当前模型输出未完成",
        "rate_limit": "当前模型受到限流",
    }.get(error_class, "当前模型未能完成请求")
    return f"{reason}，正在尝试备用模型"


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

    async def route_call(
        self, endpoints: list[ChatEndpoint], *, budget_seconds: float,
        invoke: Callable[[ChatEndpoint, float], Awaitable[T]],
        on_progress: Progress | None = None, on_trace: TraceCallback | None = None,
        preferred_provider_key: str | None = None,
    ) -> T:
        """Recover one model call; completed queries and task state stay outside.

        Every attempt includes transport retries in its absolute deadline. A
        preferred endpoint belongs to the calling task, never a global switch.
        """
        deadline = asyncio.get_running_loop().time() + min(120, max(.001, budget_seconds))
        ordered = sorted(endpoints, key=lambda item: item.key != preferred_provider_key) if preferred_provider_key else list(endpoints)
        last_error: ChatError | None = None
        for index, endpoint in enumerate(ordered):
            if not self._circuits.is_available(endpoint.key):
                if on_trace:
                    await on_trace('provider.skipped', {'provider': endpoint.name, 'reason': 'circuit_isolated'})
                await report_progress(on_progress, 'isolated', f'{endpoint.name} 正在隔离期，已跳过该服务')
                continue
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= .001:
                break
            # Keep some recovery time when a backup exists. This is an overall
            # attempt deadline, not merely httpx's socket inactivity timeout.
            reserve = min(15.0, remaining * .25) if index < len(ordered) - 1 else 0
            attempt_budget = max(.001, min(float(endpoint.timeout), remaining - reserve))
            try:
                async with asyncio.timeout(attempt_budget):
                    value = await invoke(endpoint, attempt_budget)
            except TimeoutError:
                error = ChatError('模型响应超时，本次请求未完成，请稍后重试。', 'timeout')
            except ChatError as exc:
                error = exc
            else:
                self._circuits.record_success(endpoint.key)
                if on_trace:
                    await on_trace('provider.selected', {'provider': endpoint.name, 'provider_key': endpoint.key,
                                                        'used_backup': endpoint.key != endpoints[0].key})
                return value
            last_error = _prefer_error(last_error, error)
            self._circuits.record_failure(endpoint.key, error.error_class)
            if on_trace:
                await on_trace('provider.failed', {'provider': endpoint.name, 'error_class': error.error_class,
                                                  'message': error.message})
            if index < len(ordered) - 1:
                await report_progress(on_progress, 'recovering', _failover_message(error.error_class))
        if last_error is not None:
            raise last_error
        if not endpoints:
            raise ChatError('请先配置可用的对话模型服务商。', 'config')
        if asyncio.get_running_loop().time() < deadline:
            raise ChatError('所有模型通道暂在隔离期，请稍后重试。', 'unavailable')
        raise ChatError('本次模型调用的时间预算已用尽。', 'timeout')

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
                result.last_error = _prefer_error(result.last_error, exc)
                state.trail.append(f"{endpoint.name}({exc.error_class})")
                circuit_state = self._circuits.record_failure(endpoint.key, exc.error_class)
                logger.warning(
                    "assistant.provider fail id=%s provider=%s class=%s failures=%s isolated=%s",
                    message_id or "-", endpoint.name, exc.error_class, circuit_state.failures, circuit_state.isolated,
                )
                if circuit_state.isolated:
                    await report_progress(on_progress, "isolated", f"{endpoint.name} 连续异常，已临时隔离")
                if index < len(endpoints) - 1:
                    await report_progress(on_progress, "recovering", _failover_message(exc.error_class))
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
