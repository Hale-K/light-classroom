"""Model Gateway: provider discovery, invocation, routing, and failover."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.chat import (
    ChatEndpoint,
    ChatOutcome,
    complete_chat,
    complete_chat_tools,
    resolve_chat_endpoints,
)
from app.ai.model.routing import ModelProviderRouter, ProviderRouteResult
from app.ai.resilience import ProviderCircuitBreaker
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress


T = TypeVar("T")
EndpointResolver = Callable[[AsyncSession, int], Awaitable[list[ChatEndpoint]]]
ModelCaller = Callable[..., Awaitable[Any]]


class ModelGateway:
    """The only model-facing service consumed by an Agent.

    Low-level HTTP and provider routing stay replaceable in tests and future
    deployments without leaking provider details into the Agent loop.
    """

    def __init__(
        self,
        circuits: ProviderCircuitBreaker,
        *,
        resolver: EndpointResolver | None = None,
        text_caller: ModelCaller | None = None,
        tool_caller: ModelCaller | None = None,
    ) -> None:
        self._router = ModelProviderRouter(circuits)
        self._resolver = resolver or resolve_chat_endpoints
        self._text_caller = text_caller or complete_chat
        self._tool_caller = tool_caller or complete_chat_tools

    async def resolve(self, session: AsyncSession, tenant_id: int) -> list[ChatEndpoint]:
        return await self._resolver(session, tenant_id)

    async def complete(self, **request: Any) -> str:
        return await self._text_caller(**request)

    async def complete_tools(self, **request: Any) -> ChatOutcome:
        return await self._tool_caller(**request)

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
        return await self._router.route(
            endpoints,
            total_budget_seconds=total_budget_seconds,
            invoke=invoke,
            on_progress=on_progress,
            on_trace=on_trace,
            message_id=message_id,
            clock=clock,
        )
