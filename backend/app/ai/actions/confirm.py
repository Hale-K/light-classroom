"""确认侧：老师对草稿点确认/取消后的服务端执行。

执行只接受服务端草稿 ID：核对草稿归属与有效期，规则组/课位/目标任一变更即拒绝，
追加规则与审计回执在同一事务提交，重复确认返回原回执。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from app.ai.actions.proposal import (
    RulesProposal,
    action_view,
    build_rule,
    fingerprint,
    resolve_targets,
)
from app.ai.actions.models import AiAction
from app.models.audit import AuditLog
from app.models.org import TenantConfig
from app.services.scheduling.rules import (
    RuleDefinition, RuleGroupDocument, compile_rule_group,
    dump_stored_rule_groups, parse_stored_rule_groups,
)


def check_action(action: AiAction | None, tenant_id: int, user_id: int) -> None:
    if action is None or action.tenant_id != tenant_id or action.user_id != user_id:
        raise HTTPException(404, "未找到该草稿")
    if action.status == "executed":
        return
    if action.status != "pending":
        raise HTTPException(409, "草稿已取消，请重新提出需求")
    if action.expires_at <= datetime.utcnow():
        raise HTTPException(409, "草稿已过期，请重新预览")


async def decide_action(session, tenant_id: int, user_id: int, action_id: str, decision: str) -> dict:
    from app.ai.tools.school import _term
    from app.api.v1.scheduling import SCHEDULING_RULE_GROUP_CONFIG_KEY, _load_grid_config
    action = (await session.execute(select(AiAction).where(
        AiAction.id == action_id, AiAction.tenant_id == tenant_id, AiAction.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    if action and decision == "cancel" and action.status == "cancelled":
        return action_view(action)
    check_action(action, tenant_id, user_id)
    if action.status == "executed":
        return action_view(action)
    if decision == "cancel":
        action.status = "cancelled"
        await session.commit()
        return action_view(action)
    payload = action.payload
    year, term = await _term(session, tenant_id)
    if (year, term) != (payload["academic_year"], payload["term"]):
        raise HTTPException(409, "当前学年学期已变更，请重新预览")
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id, TenantConfig.config_key == SCHEDULING_RULE_GROUP_CONFIG_KEY,
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    config = dict(row.config_value or {}) if row else {}
    scope = f"{year}:{term}"
    groups, active_id = parse_stored_rule_groups(config[scope]) if scope in config else ([], None)
    group = next((g for g in groups if g.id == payload["group_id"]), None)
    grid = await _load_grid_config(session, tenant_id, year, term, group.grade_id if group else None)
    if group is None or fingerprint(group.model_dump(mode="json")) != payload["group_hash"] or fingerprint(grid) != payload["grid_hash"]:
        raise HTTPException(409, "规则组或课位已被修改，请重新预览，避免覆盖其他老师的修改")
    requests = RulesProposal.model_validate(payload["request"])
    rules = [RuleDefinition.model_validate(r) for r in payload["rules"]]
    try:
        for request, rule in zip(requests.rules, rules, strict=True):
            ids = await resolve_targets(session, tenant_id, request)
            if ids != rule.target.ids:
                raise ValueError("目标对象已变更")
            build_rule(request, ids, grid)
    except ValueError as exc:
        raise HTTPException(409, f"{exc}，请重新预览") from exc
    old = group.model_dump(mode="json")
    updated = RuleGroupDocument.model_validate({**old, "rules": [*group.rules, *rules], "version": group.version + 1})
    compile_rule_group(updated)
    config[scope] = dump_stored_rule_groups([updated if g.id == group.id else g for g in groups], active_id)
    row.config_value = config
    row.updated_by = user_id
    row.updated_at = datetime.utcnow()
    action.status = "executed"
    action.result = {
        "text": f"已向「{group.name}」保存 {len(rules)} 条规则。请到排课页生成课表并检查冲突。",
        "path": "/scheduling?tab=rules",
        "count": len(rules),
        "verification": {
            "group_id": group.id,
            "rule_ids": [rule.id for rule in rules],
            "group_version": updated.version,
            "compiled": True,
        },
    }
    session.add(AuditLog(tenant_id=tenant_id, user_id=user_id, action="assistant.rules.confirm", resource="rule_group", old_value=old, new_value={"action_id": action.id, "group": updated.model_dump(mode="json")}))
    await session.commit()
    return action_view(action)
