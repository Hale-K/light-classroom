"""助手运行事件的稳定、可持久化表示。"""
from __future__ import annotations

from datetime import datetime


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
