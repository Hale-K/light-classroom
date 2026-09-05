"""提案侧：草稿的数据结构、构建校验，以及生成待确认草稿的 propose_rules。

模型只可通过 `propose_rules` 工具提交提案；本模块只产草稿（AiAction），不落规则。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.ai.actions.models import AiAction
from app.models.org import Subject, User
from app.services.scheduling.rules import (
    RuleDefinition, RuleGroupDocument, RuleTarget, compile_rule_group,
)


class RuleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: Literal["slot_forbidden", "teacher_forbidden_slots", "subject_consecutive", "teacher_daily_limit"]
    target_names: list[str] = Field(min_length=1, max_length=20)
    priority: Literal["hard", "soft"]
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    periods: list[int] = Field(default_factory=list, max_length=12)
    minimum_block_length: int | None = Field(default=None, ge=2, le=12)
    minimum_days: int | None = Field(default=None, ge=1, le=7)
    max_lessons_per_day: int | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def validate_fields(self):
        if any(not name.strip() for name in self.target_names):
            raise ValueError("必须填写目标名称")
        self.target_names = list(dict.fromkeys(name.strip() for name in self.target_names))
        if any(d < 1 or d > 7 for d in self.weekdays):
            raise ValueError("星期必须为 1 到 7")
        if any(p < 1 or p > 12 for p in self.periods):
            raise ValueError("节次必须为 1 到 12")
        return self


class RulesProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    group_name: str = Field(min_length=1, max_length=100)
    rules: list[RuleRequest] = Field(min_length=1, max_length=10)


PROPOSE_RULES_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_rules",
        "description": (
            "生成待老师确认的规则草稿，不保存规则。先 lookup_rules 查规则组名称。"
            "只支持白天、每周：科目禁排(slot_forbidden)、具体教师禁排(teacher_forbidden_slots)、"
            "学科连堂(subject_consecutive)、具体教师每日上限(teacher_daily_limit)。"
            "目标填写本校准确名称，同名时请老师在页面配置，不猜ID。星期节次不得臆造；"
            "强制要求用hard，偏好用soft；未说清则询问。连堂必须明确每周几天及连续几节。"
            "多条要求一次放入rules。不能处理的晚课、单双周、删除修改等需求先说明边界，不生成部分草稿冒充完整完成。"
        ),
        "parameters": RulesProposal.model_json_schema(),
    },
}


def fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build_rule(request: RuleRequest, ids: list[int], grid: dict) -> RuleDefinition:
    daily = grid.get("daily_periods") or []
    days = sorted(set(request.weekdays)) or [i + 1 for i, count in enumerate(daily) if count > 0]
    periods = sorted(set(request.periods))
    params = {}
    if not days or any(day > len(daily) or daily[day - 1] <= 0 for day in days):
        raise ValueError("指定星期没有白天课位，请核对课位结构")
    if request.code in {"slot_forbidden", "teacher_forbidden_slots"}:
        if not request.weekdays or not periods:
            raise ValueError("禁排需要明确星期和节次，请补充")
        if any(day > len(daily) or max(periods) > daily[day - 1] for day in days):
            raise ValueError("指定星期或节次超出本校白天课位，请核对课位结构")
        if any(v is not None for v in (request.minimum_days, request.minimum_block_length, request.max_lessons_per_day)):
            raise ValueError("禁排规则不能包含连堂或课时上限参数")
    elif request.code == "subject_consecutive":
        if periods or request.max_lessons_per_day is not None:
            raise ValueError("连堂暂不支持指定节次或每日上限，请分别配置")
        if request.minimum_days is None or request.minimum_block_length is None:
            raise ValueError("请明确每周至少几天连堂、连续几节")
        available = sum(1 for day in days if day <= len(daily) and daily[day - 1] >= request.minimum_block_length)
        if available < request.minimum_days:
            raise ValueError("本校白天课位无法满足所需连堂天数和长度")
        params = {"minimum_block_length": request.minimum_block_length, "minimum_days": request.minimum_days}
    else:
        if request.weekdays or periods or request.minimum_days is not None or request.minimum_block_length is not None:
            raise ValueError("教师每日上限作用于全部白天，不支持指定星期节次")
        if request.max_lessons_per_day is None:
            raise ValueError("请明确教师每天最多几节课")
        params = {"max_lessons_per_day": request.max_lessons_per_day}
    kind = "subject" if request.code in {"slot_forbidden", "subject_consecutive"} else "teacher"
    labels = {"slot_forbidden": "科目禁排", "teacher_forbidden_slots": "教师禁排", "subject_consecutive": "学科连堂", "teacher_daily_limit": "教师每日上限"}
    return RuleDefinition(
        id=uuid4().hex, title=f"{'、'.join(request.target_names)} · {labels[request.code]}"[:100],
        code=request.code, priority=request.priority, target=RuleTarget(type=kind, ids=ids),
        weekdays=days, periods=periods, params=params,
    )


async def resolve_targets(session, tenant_id: int, request: RuleRequest) -> list[int]:
    entity = Subject if request.code in {"slot_forbidden", "subject_consecutive"} else User
    scope = (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None) if entity is Subject else User.tenant_id == tenant_id
    names = list(dict.fromkeys(name.strip() for name in request.target_names))
    # Core rows keep the explicit shared-subject OR scope; the ORM tenant hook
    # otherwise narrows it again and hides the global subject dictionary.
    stmt = select(entity.__table__).where(scope, entity.name.in_(names))
    if entity is User:
        stmt = stmt.where(User.status == "active", User.role == "teacher")
    rows = (await session.execute(stmt)).all()
    ids = []
    for name in names:
        matches = [row for row in rows if row.name == name]
        if len(matches) != 1:
            raise ValueError(f"本校「{name}」{'有重名，请在页面选择具体对象' if matches else '未找到，请核对准确名称'}")
        ids.append(matches[0].id)
    return ids


def action_view(action: AiAction) -> dict:
    return {"id": action.id, "status": action.status, "summary": action.payload["summary"],
            "expires_at": action.expires_at.isoformat() + "Z", "result": action.result}


async def propose_rules(session, tenant_id: int, user_id: int, proposal: RulesProposal) -> AiAction:
    from app.ai.tools.school import _term
    from app.api.v1.scheduling import _load_grid_config, _load_rule_catalog
    year, term = await _term(session, tenant_id)
    if not year:
        raise ValueError("请先设置当前学年学期")
    groups, active_id = await _load_rule_catalog(session, tenant_id, year, term)
    matches = [g for g in groups if g.name == proposal.group_name]
    if len(matches) != 1:
        raise ValueError("规则组名称不存在或重名，请先查询并选择一个明确的规则组；没有规则组请先在排课页创建")
    group = matches[0]
    grid = await _load_grid_config(session, tenant_id, year, term)
    if not grid.get("configured"):
        raise ValueError("请先保存本学期课位结构，再配置规则")
    rules = []
    for request in proposal.rules:
        ids = await resolve_targets(session, tenant_id, request)
        rule = build_rule(request, ids, grid)
        signature = rule.model_dump(exclude={"id", "title"})
        if any(r.model_dump(exclude={"id", "title"}) == signature for r in [*group.rules, *rules]):
            raise ValueError(f"「{rule.title}」已有相同规则，不重复添加")
        rules.append(rule)
    updated = RuleGroupDocument.model_validate({**group.model_dump(), "rules": [*group.rules, *rules]})
    compiled = compile_rule_group(updated)
    new_ids = {r.id for r in rules}
    if any(c.status != "ready" for c in compiled if c.rule_id in new_ids):
        raise ValueError("规则参数尚不完整，不能生成可执行草稿")
    lines = [f"{year} 第{term}学期 · {group.name}", f"新增 {len(rules)} 条白天规则（每周生效）："]
    for request, rule in zip(proposal.rules, rules, strict=True):
        detail = "周" + "、".join("一二三四五六日"[d - 1] for d in rule.weekdays)
        if rule.periods:
            detail += " 第" + "、".join(map(str, rule.periods)) + "节"
        if rule.code == "subject_consecutive":
            detail += f"，每周至少 {rule.params['minimum_days']} 天连续 {rule.params['minimum_block_length']} 节"
        if rule.code == "teacher_daily_limit":
            detail += f"，每天最多 {rule.params['max_lessons_per_day']} 节"
        lines.append(f"• {'、'.join(request.target_names)} · {rule.title.rsplit(' · ', 1)[-1]}：{detail}；{'硬约束' if rule.priority == 'hard' else '软偏好'}")
    lines.append("仅追加以上规则，保留已有规则和当前启用组。保存后仍需在排课页生成并检查冲突。")
    if active_id != group.id:
        lines.append("该组当前未启用，保存不会自动切换启用组。")
    action = AiAction(tenant_id=tenant_id, user_id=user_id, expires_at=datetime.utcnow() + timedelta(minutes=20), payload={
        "academic_year": year, "term": term, "group_id": group.id,
        "group_hash": fingerprint(group.model_dump(mode="json")), "grid_hash": fingerprint(grid),
        "rules": [r.model_dump(mode="json") for r in rules],
        "request": proposal.model_dump(), "summary": "\n".join(lines),
    })
    session.add(action)
    await session.flush()
    return action
