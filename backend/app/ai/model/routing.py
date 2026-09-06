"""模型服务商选择与故障转移的通用状态。"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.resilience import ProviderCircuitBreaker


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

    def available(self, circuits: ProviderCircuitBreaker):
        """按配置顺序产出未隔离服务商。"""
        for index, endpoint in enumerate(self.endpoints):
            if circuits.is_available(endpoint.key):
                yield index, endpoint
            else:
                self.trail.append(f"{endpoint.name}隔离期跳过")
