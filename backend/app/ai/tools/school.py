"""教务只读 Tool：模型在工具循环里自主调用。

数字、人名、班级、规则一律以这里的查询结果为准，模型不得编造。
只读、按租户隔离、同进程直查库（不走 HTTP、不代写教务数据）。
写操作不在此层，等确认卡片机制落地后再加。
对应 Spring AI 的 Tool / FunctionCallback（后端可执行部分）。
"""
from __future__ import annotations

import json
import logging
import asyncio

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.skill.catalog import (
    OPTIONAL_BY_KEY,
    parse_picked_keys,
    retrieved_text,
    skills_for_keys,
)
from app.models.enums import BaseUserRole, UserStatus
from app.models.org import (
    Class,
    CourseHourPlan,
    Grade,
    Subject,
    TeachingAssignment,
    TenantConfig,
    User,
)
from app.services.scheduling.rules import parse_stored_rule_groups

logger = logging.getLogger(__name__)

_LIST_CAP = 15
_WEEK = "一二三四五六日"

SCHOOL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_teachers",
            "description": "查本校在职教师：按科目或姓名关键词，返回任教学科与班主任班级。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "科目名，如 数学；不按科目筛就省略"},
                    "keyword": {"type": "string", "description": "教师姓名关键词"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_schedule_setup",
            "description": "查本校排课准备度：当前学年学期、课位网格、年级班级数、课时与任教覆盖情况。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rules",
            "description": "查本校当前学年学期的规则组：每组规则数、启用与硬约束情况。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_playbook",
            "description": "取说明书正文（操作步骤细节）。编号必须来自 system 里的说明书目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": '目录编号，如 ["05-rules"]，最多 2 个',
                    }
                },
            },
        },
    },
]

for _tool in SCHOOL_TOOLS:
    if _tool["function"]["name"] in {"lookup_schedule_setup", "lookup_rules"}:
        _tool["function"]["parameters"]["properties"] = {
            "academic_year": {"type": "string", "description": "查询学年；默认当前页面学年，否则本校当前学年"},
            "term": {"type": "string", "description": "查询学期"},
            **({"class_id": {"type": "integer", "description": "只查询一个班时填写页面或查询确认的班级ID；不填查全校"}} if _tool["function"]["name"] == "lookup_schedule_setup" else {}),
        }
SCHOOL_TOOLS.append({"type": "function", "function": {
    "name": "lookup_generation_status", "description": "查询本校已有排课生成长任务的真实状态；默认使用当前页面任务编号，不发起生成。",
    "parameters": {"type": "object", "properties": {"job_id": {"type": "string", "description": "已知任务编号，不得编造；当前页有任务时可省略"}}},
}})


def _args(arguments: str) -> dict:
    try:
        data = json.loads((arguments or "{}").strip() or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _when(weekdays: list[int], periods: list[int]) -> str:
    days = "、".join(f"周{_WEEK[w - 1]}" for w in weekdays if 1 <= w <= 7)
    slots = "第" + "、".join(str(p) for p in periods) + "节" if periods else ""
    return "，".join(bit for bit in (days, slots) if bit)


async def _term(session: AsyncSession, tenant_id: int) -> tuple[str, str]:
    """当前学年学期，复用教师档案的系统设置兼容逻辑。"""
    from app.api.v1.teacher_profiles import _defaults

    d = await _defaults(session, tenant_id)
    return str(d.get("academic_year") or ""), str(d.get("term") or "1")


async def lookup_teachers(
    session: AsyncSession,
    tenant_id: int,
    *,
    subject: str = "",
    keyword: str = "",
    academic_year=None, term=None,
) -> str:
    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.role == BaseUserRole.teacher,
        User.status == UserStatus.active,
    )
    keyword = (keyword or "").strip()
    if keyword:
        stmt = stmt.where(User.name.contains(keyword))
    teachers = (await session.execute(stmt)).scalars().all()
    if not teachers:
        return f"{year or '当前学年'}第{term}学期没有匹配「{keyword}」的在职教师。"
    ids = [t.id for t in teachers if t.id is not None]

    subject_rows = (await session.execute(select(Subject.__table__).where(
        (Subject.tenant_id == tenant_id) | (Subject.tenant_id.is_(None)),
    ))).all()
    subject_names = {s.id: s.name for s in subject_rows}

    want = (subject or "").strip()
    subject_ids: set[int] | None = None
    if want:
        subject_ids = {s.id for s in subject_rows if want in s.name or s.name in want}
        if not subject_ids:
            return f"科目库里没有「{want}」。请先在科目管理建好，或换一个本校在用的科目名。"

    where = [
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.teacher_id.in_(ids),
    ]
    if year:
        where.append(TeachingAssignment.academic_year == year)
    where.append(TeachingAssignment.term == term)
    asg_rows = (await session.execute(select(TeachingAssignment).where(*where))).scalars().all()

    head_rows = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.head_teacher_id.in_(ids),
    ))).scalars().all()
    head_classes: dict[int, list[str]] = {}
    for c in head_rows:
        if c.head_teacher_id is not None:
            head_classes.setdefault(c.head_teacher_id, []).append(c.name)

    # 班主任一览：完整列出、不受明细行数上限影响——「班主任有哪些」一类问题的答案在这里
    head_ids = sorted({c.head_teacher_id for c in head_rows if c.head_teacher_id is not None})
    head_names: dict[int, str] = {}
    if head_ids:
        head_names = dict((await session.execute(
            select(User.id, User.name).where(User.id.in_(head_ids))
        )).all())
    head_pairs = [
        f"{c.name} {head_names[c.head_teacher_id]}"
        for c in sorted(head_rows, key=lambda c: c.name)
        if c.head_teacher_id is not None and head_names.get(c.head_teacher_id)
    ]

    taught: dict[int, set[str]] = {}
    for a in asg_rows:
        if a.teacher_id is None:
            continue
        if subject_ids is not None and a.subject_id not in subject_ids:
            continue
        name = subject_names.get(a.subject_id)
        if name:
            taught.setdefault(a.teacher_id, set()).add(name)

    lines: list[str] = []
    for t in teachers:
        if t.id is None:
            continue
        if subject_ids is not None and t.id not in taught:
            continue
        bits = ["、".join(sorted(taught.get(t.id) or [])) or "暂无任教"]
        if head := head_classes.get(t.id):
            bits.append("、".join(head[:4]) + "班主任")
        lines.append(f"- {t.name}：{'；'.join(bits)}")
    scope = f"任教「{want}」的" if want else "在职教师"
    total = len(lines)
    more = max(0, total - _LIST_CAP)
    tail = f"（其余 {more} 人略）" if more > 0 else ""
    head_line = f"{year or '当前学年'}第{term}学期，{scope}共 {total} 人{tail}："
    overview = (
        f"班主任一览（{len(head_pairs)} 个班）：{'；'.join(head_pairs)}"
        if head_pairs
        else "班主任一览：还没有班级设置班主任。"
    )
    return head_line + "\n" + overview + "\n" + "\n".join(lines[:_LIST_CAP])


async def lookup_schedule_setup(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, class_id=None) -> str:
    from app.api.v1.scheduling import _load_grid_config, _load_rule_catalog
    from app.ai.tools.readiness import readiness_lines
    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"
    grid = await _load_grid_config(session, tenant_id, year, term)
    stmt = select(Class).where(Class.tenant_id == tenant_id)
    if class_id is not None:
        stmt = stmt.where(Class.id == int(class_id))
    classes = (await session.execute(stmt)).scalars().all()
    if class_id is not None and not classes:
        return "本校未找到指定班级，请重新选择班级。"
    plans = (await session.execute(select(CourseHourPlan).where(CourseHourPlan.tenant_id == tenant_id, CourseHourPlan.academic_year == year, CourseHourPlan.term == term))).scalars().all()
    assignments = (await session.execute(select(TeachingAssignment).where(TeachingAssignment.tenant_id == tenant_id, TeachingAssignment.academic_year == year, TeachingAssignment.term == term))).scalars().all()
    subjects = (await session.execute(select(Subject.__table__).where((Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None)))).all()
    groups, active_id = await _load_rule_catalog(session, tenant_id, year, term)
    active = next((g.name for g in groups if g.id == active_id), "未选择")
    return "\n".join([f"{year}学年第{term}学期。", *readiness_lines(classes, plans, assignments, subjects, grid), f"规则组共 {len(groups)} 个，当前启用：{active}。" + ("请先到规则组建立适用年级的规则。" if not groups else "")])


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


def lookup_playbook(arguments: str) -> str:
    keys: list[str] = []
    raw = _args(arguments).get("keys")
    if isinstance(raw, list):
        keys = [str(k).strip() for k in raw if str(k).strip()]
    docs = skills_for_keys(keys) or skills_for_keys(parse_picked_keys(arguments or ""))
    if not docs:
        known = "、".join(sorted(OPTIONAL_BY_KEY)[:6]) + " 等"
        return f"编号没有对上说明书目录（有 {known}）。请从 system 目录里选 1~2 个编号再调一次。"
    return retrieved_text([d.key for d in docs])


async def execute_school_tool(
    name: str,
    arguments: str,
    *,
    session: AsyncSession,
    tenant_id: int,
    page_context: dict | None = None,
) -> str:
    """执行一个教务只读工具，返回给模型看的文本。

    这里的工具全部只读，因此仅对连接和超时做一次短退避重试；参数和业务错误
    不重试，直接交给模型澄清。规则草稿与确认写入不经过本函数。
    """
    async def dispatch() -> str:
        context = page_context or {}
        args = _args(arguments)
        scope = {"academic_year": args.get("academic_year") or context.get("academic_year"), "term": args.get("term") or context.get("term")}
        if name == "lookup_generation_status":
            return await lookup_generation_status(str(args.get("job_id") or context.get("job_id") or ""), tenant_id)
        if name == "lookup_teachers":
            return await lookup_teachers(session, tenant_id, subject=str(args.get("subject") or ""), keyword=str(args.get("keyword") or ""), **scope)
        if name == "lookup_schedule_setup":
            return await lookup_schedule_setup(session, tenant_id, class_id=args.get("class_id"), **scope)
        if name == "lookup_rules":
            return await lookup_rules(session, tenant_id, rule_group_id=args.get("rule_group_id") or context.get("rule_group_id"), **scope)
        if name == "lookup_playbook":
            return lookup_playbook(arguments)
        names = ", ".join(t["function"]["name"] for t in SCHOOL_TOOLS)
        return f"没有名为「{name}」的工具。可用工具：{names}"

    try:
        return await dispatch()
    except (TimeoutError, ConnectionError) as exc:
        logger.warning("assistant.tool transient_retry name=%s error=%s", name, type(exc).__name__)
        try:
            await asyncio.sleep(0.2)
            return await dispatch()
        except Exception:
            logger.exception("assistant.tool retry_fail name=%s", name)
            return f"工具 {name} 暂时无法连接。请稍后重试，或让老师自己到对应页面核对。"
    except Exception:
        logger.exception("assistant.tool fail name=%s args=%s", name, (arguments or "")[:120])
        return f"工具 {name} 查询失败。请换个问法，或让老师自己到对应页面核对。"


async def lookup_generation_status(job_id: str, tenant_id: int) -> str:
    import asyncio
    import re
    import time
    from app.services.scheduling.generate_jobs import _redis, _job_key, get_job
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        return "请先到排课页选择或发起生成任务，再查询进度；当前没有可核对的任务编号。"
    def snapshot():
        client = _redis()
        if client is not None:
            raw = client.get(_job_key(job_id))
            return json.loads(raw) if raw else None
        job = get_job(job_id)
        return job._snapshot() if job else None
    job = await asyncio.wait_for(asyncio.to_thread(snapshot), timeout=5)
    if not job or job.get("tenant_id") != tenant_id:
        return "本校未找到该生成任务，任务可能已过期。请到排课页核对，不要据此重复生成。"
    latest = (job.get("history") or [{}])[-1]
    age = max(0, int(time.time() - latest.get("ts", job.get("created_at", time.time()))))
    labels = {"queued": "等待后台处理", "running": "正在生成", "done": "生成已完成", "error": "生成失败"}
    result = job.get("result") or {}
    return "\n".join([f"生成任务：{labels.get(job['status'], '状态待核对')}。", f"最近一次进展在 {age} 秒前：{latest.get('message') or '尚未收到求解进度'}。", "超过30秒没有进展时，只能说暂未收到更新，不能断言后台仍正常运行。" if age > 30 and job['status'] in ('queued', 'running') else "", f"已生成课节数：{result.get('created', '尚未返回')}。生成完成仍须检查未排课量和硬约束。", "取消助手查询不会取消排课生成任务。"])
