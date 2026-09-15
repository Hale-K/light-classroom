"""Agent Inbox：把用户追加指令和运行时上下文分成明确的消费语义。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

InboxKind = Literal["followup", "steer", "inject"]


@dataclass(frozen=True)
class InboxMessage:
    id: str
    kind: InboxKind
    content: str | dict[str, Any]
    wake: bool
    boundary: Literal["turn", "step"]


def receive(kind: InboxKind, content: str | dict[str, Any]) -> dict[str, Any]:
    """构造持久化事件；事件本身就是事实，不依赖内存队列。"""
    if kind == "followup":
        wake, boundary = True, "turn"
    elif kind == "steer":
        wake, boundary = True, "step"
    else:
        wake, boundary = False, "step"
    return {
        "type": "assistant.inbox.received",
        "phase": "inbox",
        "source": "user" if kind != "inject" else "context",
        "visibility": "internal",
        "message": f"已收到{ {'followup': '追加任务', 'steer': '方向调整', 'inject': '上下文补充'}[kind] }",
        "data": {
            "id": uuid4().hex,
            "kind": kind,
            "content": content,
            "wake": wake,
            "boundary": boundary,
            "consumed": False,
        },
        "at": datetime.utcnow().isoformat() + "Z",
    }


def consume(events: list[dict], boundary: Literal["turn", "step"]) -> list[InboxMessage]:
    """消费当前边界可见的消息，并原地标记，避免重复执行。"""
    consumed: list[InboxMessage] = []
    for event in events:
        if event.get("type") != "assistant.inbox.received":
            continue
        data = event.get("data") or {}
        if data.get("consumed") or data.get("boundary") != boundary:
            continue
        data["consumed"] = True
        data["consumed_at"] = datetime.utcnow().isoformat() + "Z"
        consumed.append(InboxMessage(
            id=str(data.get("id") or ""),
            kind=data["kind"],
            content=data.get("content") or "",
            wake=bool(data.get("wake")),
            boundary=data["boundary"],
        ))
    return consumed
