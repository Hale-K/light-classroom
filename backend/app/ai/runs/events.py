"""助手运行事件的稳定、可持久化表示。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
import hashlib
import json
from typing import Any

TraceCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


def run_event(phase: str, message: str, *, at: datetime | None = None) -> dict:
    """构造可供前端、日志和后续指标共同消费的低基数事件。"""
    occurred_at = at or datetime.utcnow()
    source = "tool" if phase in {"tool", "observed"} else "model" if phase in {"model", "detecting", "recovering", "isolated", "degraded"} else "run"
    return {
        "type": f"assistant.{phase}",
        "phase": phase,
        "source": source,
        "message": message[:300],
        "at": occurred_at.isoformat() + "Z",
    }


def trace_event(kind: str, data: dict[str, Any], *, at: datetime | None = None) -> dict:
    """构造仅供任务回放的事件，不作为面向老师的进度文案。"""
    occurred_at = at or datetime.utcnow()
    return {
        "type": f"assistant.{kind}",
        "phase": "trace",
        "source": "session" if kind.startswith("session.") else "tool" if kind.startswith("tool.") else "model",
        "message": "已记录运行轨迹",
        "visibility": "internal",
        "data": _diagnostic_data(kind, data),
        "at": occurred_at.isoformat() + "Z",
    }


def _diagnostic_data(kind: str, data: dict) -> dict:
    """Persist metadata by default; never duplicate full model/student context."""
    if kind in {'model.request', 'model.response', 'session.turn', 'tool.result'}:
        serialized = json.dumps(data, ensure_ascii=False, default=str)
        return {'content_omitted': True, 'chars': len(serialized),
                'sha256': hashlib.sha256(serialized.encode('utf-8')).hexdigest(),
                **{key: data[key] for key in ('step', 'final', 'tools_enabled', 'name', 'id') if key in data},
                'tool_names': [item.get('name') for item in data.get('tool_calls', [])]}
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    if len(serialized) > 12000:
        return {'content_omitted': True, 'chars': len(serialized),
                'sha256': hashlib.sha256(serialized.encode('utf-8')).hexdigest()}
    return data
