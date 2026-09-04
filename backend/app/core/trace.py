"""请求级 trace_id：日志、响应头、前端报错共用同一条。"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import Request
from loguru import logger

TRACE_HEADER = "X-Trace-Id"

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def current_trace_id() -> str:
    value = trace_id_ctx.get()
    return value if value and value != "-" else "-"


def resolve_trace_id(request: Request) -> str:
    incoming = (
        request.headers.get(TRACE_HEADER)
        or request.headers.get("X-Request-Id")
        or ""
    ).strip()
    if incoming and len(incoming) <= 64:
        return incoming
    return new_trace_id()


async def trace_middleware(request: Request, call_next):
    trace_id = resolve_trace_id(request)
    token = trace_id_ctx.set(trace_id)
    try:
        with logger.contextualize(trace_id=trace_id):
            response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response
    finally:
        trace_id_ctx.reset(token)
