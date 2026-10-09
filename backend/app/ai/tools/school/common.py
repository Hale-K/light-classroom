"""教务工具的共享助手：参数解析、统一响应、范围与学期口径。"""
from __future__ import annotations

import json

from sqlmodel.ext.asyncio.session import AsyncSession

_LIST_CAP = 15
_WEEK = "一二三四五六日"


def _args(arguments: str) -> dict:
    try:
        data = json.loads((arguments or "{}").strip() or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _tool_response(
    name: str,
    *,
    message: str,
    ok: bool = True,
    code: str = "OK",
    data: object = None,
    scope: dict | None = None,
    retryable: bool = False,
) -> str:
    """统一 Agent 工具响应；data 初期保留文本，便于兼容现有查询实现。"""
    status = "success" if ok else "error"
    if ok and code == "EMPTY_RESULT":
        status = "empty"
    return json.dumps({
        "ok": ok,
        "status": status,
        "code": code,
        "message": message,
        "data": data if data is not None else {"text": message} if ok else None,
        "scope": scope or {},
        "retryable": retryable,
        "meta": {"tool": name},
    }, ensure_ascii=False)


def _tool_scope(args: dict, page_context: dict | None) -> dict:
    context = page_context or {}
    return {
        key: args.get(key) or context.get(key)
        for key in ("academic_year", "term", "class_id", "rule_group_id", "job_id")
        if args.get(key) or context.get(key)
    }


def _when(weekdays: list[int], periods: list[int]) -> str:
    days = "、".join(f"周{_WEEK[w - 1]}" for w in weekdays if 1 <= w <= 7)
    slots = "第" + "、".join(str(p) for p in periods) + "节" if periods else ""
    return "，".join(bit for bit in (days, slots) if bit)


async def _term(session: AsyncSession, tenant_id: int) -> tuple[str, str]:
    """当前学年学期，复用教师档案的系统设置兼容逻辑。"""
    from app.api.v1.teacher_profiles import _defaults

    d = await _defaults(session, tenant_id)
    return str(d.get("academic_year") or ""), str(d.get("term") or "1")
