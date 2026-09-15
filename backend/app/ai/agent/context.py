"""教务 Agent 的消息上下文处理。"""
from __future__ import annotations

BLOCKED_DESTRUCTIVE_REQUESTS = ("删除数据库", "清空数据库", "drop database", "truncate table", "delete from", "删库", "清空所有数据", "删除全部学生", "删除全部教师", "执行任意sql", "运行shell")


def blocked_destructive_request(text: str) -> bool:
    normalized = (text or "").strip().lower().replace("\u3000", " ")
    return any(marker in normalized for marker in BLOCKED_DESTRUCTIVE_REQUESTS)


def last_user_message(turns: list[dict]) -> str:
    return next((str(item.get("content") or "") for item in reversed(turns) if item.get("role") == "user"), "")


def trim_turns(turns: list[dict], keep: int = 6) -> list[dict]:
    tail = list(turns[-keep:])
    while len(tail) > 1 and tail[0].get("role") != "user":
        tail.pop(0)
    return tail
