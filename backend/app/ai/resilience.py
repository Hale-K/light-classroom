"""Provider fault detection, isolation, and recovery for the teaching assistant."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.config import settings


_IMMEDIATE_ISOLATION = {"auth", "config", "quota"}
# 计入熔断的健康类故障。请求形态类（bad_request/parse/empty/context_overflow/exhausted）
# 是对话或参数问题，不计入：否则两个超长对话就能把主模型隔离 60 秒，全校被路由到备用。
_HEALTH_FAILURES = {"network", "unavailable", "rate_limit", "timeout"}


@dataclass(frozen=True)
class CircuitSnapshot:
    failures: int = 0
    isolated_until: float = 0.0

    @property
    def isolated(self) -> bool:
        return self.isolated_until > 0


class ProviderCircuitBreaker:
    """Small process-local circuit breaker; provider failover remains available without Redis."""

    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: float = 60) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1.0, cooldown_seconds)
        self._states: dict[str, CircuitSnapshot] = {}
        self._lock = threading.Lock()

    def snapshot(self, key: str) -> CircuitSnapshot:
        with self._lock:
            return self._states.get(key, CircuitSnapshot())

    def is_available(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        state = self.snapshot(key)
        return not state.isolated or current >= state.isolated_until

    def record_failure(
        self,
        key: str,
        error_class: str,
        *,
        now: float | None = None,
    ) -> CircuitSnapshot:
        """健康类故障累计计数，配置类立即隔离；请求形态类不计数，原样返回当前快照。"""
        current = time.monotonic() if now is None else now
        with self._lock:
            previous = self._states.get(key, CircuitSnapshot())
            if error_class not in _IMMEDIATE_ISOLATION and error_class not in _HEALTH_FAILURES:
                return previous
            failures = previous.failures + 1
            isolate = error_class in _IMMEDIATE_ISOLATION or failures >= self.failure_threshold
            state = CircuitSnapshot(
                failures=failures,
                isolated_until=current + self.cooldown_seconds if isolate else 0.0,
            )
            self._states[key] = state
            return state

    def record_success(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._states.clear()


provider_circuits = ProviderCircuitBreaker(
    failure_threshold=settings.assistant_provider_failure_threshold,
    cooldown_seconds=settings.assistant_provider_cooldown_seconds,
)
