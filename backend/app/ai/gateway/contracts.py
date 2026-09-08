"""Stable service contracts consumed by the Agent runtime."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.chat import ChatEndpoint, ChatOutcome
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress


class ModelGatewayService(Protocol):
    async def resolve(self, session: AsyncSession, tenant_id: int) -> list[ChatEndpoint]: ...

    async def complete(self, **request: Any) -> str: ...

    async def complete_tools(self, **request: Any) -> ChatOutcome: ...

    async def route(
        self,
        endpoints: list[ChatEndpoint],
        *,
        total_budget_seconds: int,
        invoke: Callable[[ChatEndpoint], Awaitable[Any]],
        on_progress: Progress | None = None,
        on_trace: TraceCallback | None = None,
        message_id: str | None = None,
        clock: Callable[[], float] = ...,
    ) -> Any: ...


class ToolScopeService(Protocol):
    plan: dict | None

    @property
    def definitions(self) -> list[dict]: ...

    async def execute(self, name: str, arguments: str) -> str: ...


class ToolGatewayService(Protocol):
    def open_scope(
        self,
        *,
        session: AsyncSession,
        tenant_id: int,
        user_id: int | None,
        can_manage_rules: bool,
        page_context: dict | None,
        on_trace: TraceCallback | None = None,
    ) -> ToolScopeService: ...
