"""规则职责：规则组与已启用规则的只读查询。"""
from __future__ import annotations

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Grade, TenantConfig
from app.services.scheduling.rules import parse_stored_rule_groups
from app.ai.tools.school.common import _LIST_CAP, _term, _when

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_rules",
            "description": "只读查询本校指定学年学期的规则组和已启用规则。省略规则组时返回概况及当前启用组；指定 rule_group_id 时返回该组详情，不创建或修改规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "academic_year": {"type": "string", "description": "查询学年；默认当前页面学年，否则本校当前学年"},
                    "term": {"type": "string", "description": "查询学期"},
                    "rule_group_id": {"type": "integer", "description": "指定规则组 ID；省略时查询当前启用规则组"},
                },
                "additionalProperties": False,
            },
        },
    },
]


async def lookup_rules(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, rule_group_id=None) -> str:
    from app.api.v1.scheduling import SCHEDULING_RULE_GROUP_CONFIG_KEY

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == SCHEDULING_RULE_GROUP_CONFIG_KEY,
    ))).scalars().first()
    saved = row.config_value if row and isinstance(row.config_value, dict) else {}
    value = saved.get(f"{year}:{term}")
    groups, active_id = parse_stored_rule_groups(value) if isinstance(value, dict) else ([], None)
    if not groups:
        return f"{year}学年第{term}学期还没有规则组。请到排课「规则组」添加。"

    grade_rows = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    grade_names = {g.id: g.name for g in grade_rows}
    lines = [f"{year}学年第{term}学期共 {len(groups)} 个规则组："]
    for g in groups:
        enabled = sum(1 for r in g.rules if r.enabled)
        hard = sum(1 for r in g.rules if r.enabled and r.priority == "hard")
        grade = grade_names.get(g.grade_id or -1, "全校")
        mark = "（当前启用）" if g.id == active_id else ""
        lines.append(
            f"- {g.name}［{grade}］规则 {len(g.rules)} 条，启用 {enabled}（硬 {hard}）{mark}"
        )
    active = next((g for g in groups if g.id == (rule_group_id or active_id)), None)
    if active is None:
        return "\n".join(lines + ["未找到所选规则组，请确认组名后再查询详细规则。"])
    live = [r for r in active.rules if r.enabled]
    if live:
        lines.append(f"「{active.name}」已启用的规则：")
        for r in live[:_LIST_CAP]:
            when = _when(r.weekdays, r.periods)
            lines.append(f"- {r.title}（{'硬' if r.priority == 'hard' else '软'}{('，' + when) if when else ''}）")
        if len(live) > _LIST_CAP:
            lines.append(f"（其余 {len(live) - _LIST_CAP} 条略）")
    return "\n".join(lines)
