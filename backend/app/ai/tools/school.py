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
            "description": "只读查询本校当前学年学期的在职教师。可按科目或姓名关键词筛选，返回任教学科和班主任班级；不返回排课结果，也不执行修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "本校科目名，如“数学”；不筛选时省略"},
                    "keyword": {"type": "string", "description": "教师姓名关键词；不筛选时省略"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_schedule_setup",
            "description": "只读检查本校指定学年学期的排课准备度，返回课位网格、班级、课时方案、任教覆盖和规则组概况。准备度不等于一定可排且不保证无冲突。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rules",
            "description": "只读查询本校指定学年学期的规则组和已启用规则。省略规则组时返回概况及当前启用组；指定 rule_group_id 时返回该组详情，不创建或修改规则。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_subject_capacity",
            "description": "只读容量验算：按年级统计各科目的班级数、周课时合计、任课教师数，以及硬性「学科课位限制」允许课位数。用于判断某科课时需求能否排进限排课位（例如：每班 2 节但只允许 2 个课位、10 个班仅 3 位教师 ⇒ 必然无解）。不执行修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "grade": {"type": "string", "description": "年级名，如“高一”；省略时统计全校"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_slot_role_capacity",
            "description": "只读验算「课位需指定教师角色」类硬规则（如某些课位必须由班主任上课）：按规则圈定的课位计算每班需要的节数，逐班对比该班班主任对本班的实际周课时，并核对班主任并行数量是否足够。用于判断该规则是否必然无解。不执行修改。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_remaining_capacity",
            "description": "只读计算：按班级对比课位结构容量与已排课时，给出每班剩余可排节数和已设科目明细。用于回答「还能加几门科目、新科目每班该设多少节」这类规划问题。不执行修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "grade": {"type": "string", "description": "年级名，如“高一”；省略时统计全校"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_generation_log",
            "description": "只读读取本校排课生成长任务的求解事件日志（最近 40 条：阶段/进度/消息原文）。用于分析生成过程与失败过程。不会发起、重试或取消生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{32}$",
                        "description": "已知任务编号；不得编造。当前页面已有任务时可省略。",
                    }
                },
                "additionalProperties": False,
            },
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
                        "minItems": 1,
                        "maxItems": 2,
                        "description": '来自 system 说明书目录的编号，如 ["05-rules"]；目录中不存在的编号不要猜。',
                    }
                },
                "required": ["keys"],
                "additionalProperties": False,
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
        _tool["function"]["parameters"]["additionalProperties"] = False
        if _tool["function"]["name"] == "lookup_rules":
            _tool["function"]["parameters"]["properties"]["rule_group_id"] = {
                "type": "integer",
                "description": "指定规则组 ID；省略时查询当前启用规则组",
            }
SCHOOL_TOOLS.append({"type": "function", "function": {
    "name": "lookup_generation_status",
    "description": "只读查询本校已有排课生成长任务的真实状态；使用明确提供的 job_id，否则使用当前页面任务编号。不会发起、重试或取消生成。",
    "parameters": {
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "pattern": "^[a-f0-9]{32}$",
                "description": "已知任务编号；不得编造。当前页面已有任务时可省略。",
            }
        },
        "additionalProperties": False,
    },
}})

SCHOOL_TOOLS.append({"type": "function", "function": {
    "name": "lookup_walk_classes",
    "description": "只读核对已保存走班教学班：班数、班额、实际入班人数、固定任课教师、配置课时、已排课节、课表教师是否与任课关系一致；按同科教师汇总课时和人数。必须明确年级，不重分班、不改教师、不重新排课。人数为零可能是尚未入班，不代表生成失败；结果不包含未保存预览。",
    "parameters": {"type": "object", "properties": {
        "academic_year": {"type": "string"}, "term": {"type": "string", "enum": ["1", "2"]},
        "grade_id": {"type": "integer", "description": "已确认的年级ID；默认当前页面年级"},
        "grade": {"type": "string", "description": "未知道ID时提供年级名称，如高一"},
        "subject": {"type": "string", "description": "科目名称；省略查询该年级全部走班科目"},
    }, "additionalProperties": False},
}})


async def lookup_walk_classes(session: AsyncSession, tenant_id: int, *, academic_year=None,
                              term=None, grade_id=None, grade=None, subject=None) -> str:
    from app.models.gaokao import TeachingClass, TeachingClassStudent, TeachingClassSchedule

    scope = {"academic_year": academic_year, "term": term, "grade_id": grade_id}
    grades = list((await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all())
    matches = [g for g in grades if g.id == grade_id] if grade_id is not None else [
        g for g in grades if grade and str(grade).strip() in g.name
    ]
    if len(matches) != 1:
        return _tool_response('lookup_walk_classes', ok=False, code='MISSING_SCOPE',
            message='请明确要核对的年级；名称匹配多个年级时请提供具体年级。', scope=scope)
    grade_id = matches[0].id
    if not academic_year or not term:
        current_year, current_term = await _term(session, tenant_id)
        academic_year, term = academic_year or current_year, term or current_term
    scope = {"academic_year": academic_year, "term": term, "grade_id": grade_id,
             "grade": matches[0].name, "subject": subject}
    if not academic_year:
        return _tool_response('lookup_walk_classes', ok=False, code='MISSING_SCOPE',
            message='请明确学年学期后再核对走班数据。', scope=scope)
    subjects = list((await session.execute(select(Subject).where(
        (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None)
    ))).scalars().all())
    subject_names = {s.id: s.name for s in subjects}
    stmt = select(TeachingClass).where(TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == grade_id, TeachingClass.academic_year == academic_year,
        TeachingClass.term == term)
    if subject:
        stmt = stmt.where(TeachingClass.subject_id.in_([s.id for s in subjects if s.name == str(subject).strip()]))
    classes = list((await session.execute(stmt.order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars().all())
    if not classes:
        return _tool_response('lookup_walk_classes', code='EMPTY_RESULT',
            message='该范围没有已保存教学班；不能据此断言未保存预览中也没有教学班。', scope=scope)
    ids = [c.id for c in classes]
    members = (await session.execute(select(TeachingClassStudent).where(
        TeachingClassStudent.tenant_id == tenant_id, TeachingClassStudent.teaching_class_id.in_(ids)
    ))).scalars().all()
    schedules = (await session.execute(select(TeachingClassSchedule).where(
        TeachingClassSchedule.tenant_id == tenant_id, TeachingClassSchedule.teaching_class_id.in_(ids),
        TeachingClassSchedule.academic_year == academic_year, TeachingClassSchedule.term == term
    ))).scalars().all()
    teachers = (await session.execute(select(User).where(User.tenant_id == tenant_id,
        User.id.in_([c.teacher_id for c in classes if c.teacher_id is not None])))).scalars().all()
    teacher_names = {t.id: t.name for t in teachers}
    members_by_class = {cid: set() for cid in ids}
    slots_by_class = {cid: [] for cid in ids}
    for member in members:
        members_by_class[member.teaching_class_id].add(member.student_id)
    for slot in schedules:
        slots_by_class[slot.teaching_class_id].append(slot)
    class_data, loads, student_sets = [], {}, {}
    for c in classes:
        people = members_by_class[c.id]
        slots = slots_by_class[c.id]
        class_data.append({"class_id": c.id, "class_name": c.name, "subject_id": c.subject_id,
            "subject": subject_names.get(c.subject_id, '未知科目'), "capacity": c.capacity,
            "student_count": len(people), "teacher_id": c.teacher_id,
            "teacher_name": teacher_names.get(c.teacher_id), "configured_weekly_periods": c.weekly_periods,
            "scheduled_periods": len(slots),
            "scheduled_teacher_mismatch_count": sum(s.teacher_id != c.teacher_id for s in slots)})
        if c.teacher_id is None:
            continue
        key = (c.subject_id, c.teacher_id)
        load = loads.setdefault(key, {"subject": subject_names.get(c.subject_id, '未知科目'),
            "teacher_id": c.teacher_id, "teacher_name": teacher_names.get(c.teacher_id),
            "class_count": 0, "configured_weekly_periods": 0, "student_enrollments": 0})
        load['class_count'] += 1
        load['configured_weekly_periods'] += c.weekly_periods
        load['student_enrollments'] += len(people)
        student_sets.setdefault(key, set()).update(people)
    for key, load in loads.items():
        load['unique_students'] = len(student_sets[key])
    return _tool_response('lookup_walk_classes', scope=scope,
        message='已核对保存的走班数据，不含行政课和未保存预览。只比较同科教师；配置课时不等于已排课节，人次不等于去重人数。零人数可能尚未入班；班额仅展示存储值，未据此判定浮动班额违规。未验证全部硬约束或求解可行性。',
        data={"class_count": len(classes), "unassigned_classes": sum(c.teacher_id is None for c in classes),
              "classes": class_data[:100], "classes_truncated": len(classes) > 100,
              "teachers": list(loads.values())})


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


async def lookup_subject_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, grade=None) -> str:
    """容量验算数据：按年级聚合各科 班级数/周课时/教师数 + 硬性学科限排课位。

    供模型判断「某科课时需求能否排进限排课位」：限排课位数 < 该科每班周课时，
    或 教师并行容量（课位数 × 教师数）< 周课时合计 ⇒ 必然无解。
    """
    from collections import defaultdict

    from app.api.v1.scheduling import _load_rule_catalog
    from app.services.scheduling.rules import generation_subject_allowed_slots

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"

    grade_id = None
    grade_rows = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    if grade:
        matched = next((g for g in grade_rows if grade in g.name), None)
        if matched is None:
            names = "、".join(g.name for g in grade_rows) or "暂无"
            return f"没有找到名称含「{grade}」的年级。现有年级：{names}。"
        grade_id = matched.id
    classes = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.academic_year == year, Class.term == term,
    ))).scalars().all()
    if grade_id is not None:
        classes = [c for c in classes if c.grade_id == grade_id]
    if not classes:
        return "该范围内还没有班级，无法统计科目容量。请先完成班级划分。"
    class_ids = [c.id for c in classes]

    plans = (await session.execute(select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == year, CourseHourPlan.term == term,
        CourseHourPlan.class_id.in_(class_ids)))).scalars().all()
    assignments = (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == year, TeachingAssignment.term == term,
        TeachingAssignment.class_id.in_(class_ids)))).scalars().all()
    subjects = {s.id: s.name for s in (await session.execute(select(Subject))).scalars().all()}

    by_subject: dict[int, dict] = {}
    max_per_class: dict[int, float] = {}
    for p in plans:
        d = by_subject.setdefault(p.subject_id, {"classes": set(), "periods": 0.0})
        d["classes"].add(p.class_id)
        periods = float(p.weekly_periods or 0)
        d["periods"] += periods
        max_per_class[p.subject_id] = max(max_per_class.get(p.subject_id, 0), periods)
    teachers_by_subject: dict[int, set[int]] = {}
    for a in assignments:
        if a.teacher_id is not None:
            teachers_by_subject.setdefault(a.subject_id, set()).add(a.teacher_id)

    groups, _active_id = await _load_rule_catalog(session, tenant_id, year, term)
    allowed: dict[int, set[tuple[int, int]]] = {}
    for group in groups:
        if group.grade_id is not None and group.grade_id != grade_id:
            continue
        for sid, pairs in generation_subject_allowed_slots(group).items():
            allowed.setdefault(sid, set()).update(pairs)

    def _when(pairs: set[tuple[int, int]]) -> str:
        by_day: dict[int, list[int]] = {}
        for wd, period in pairs:
            by_day.setdefault(wd, []).append(period)
        return "；".join(
            f"周{_WEEK[day]}第{'、'.join(str(p) for p in sorted(periods))}节"
            for day, periods in sorted(by_day.items())
        )

    scope_label = f"·{next((g.name for g in grade_rows if g.id == grade_id), grade or '')}" if grade_id is not None else "·全校"
    lines = [f"{year}学年第{term}学期{scope_label}，共 {len(class_ids)} 个班。各科目容量验算："]
    for sid, d in sorted(by_subject.items(), key=lambda kv: -kv[1]["periods"]):
        name = subjects.get(sid, f"科目{sid}")
        teacher_count = len({t for t in teachers_by_subject.get(sid, set())})
        pairs = allowed.get(sid)
        limit = f"限排课位 {len(pairs)} 个（{_when(pairs)}）" if pairs else "未限排课位"
        hint = ""
        if pairs:
            demand = d["periods"]
            capacity = len(pairs) * teacher_count
            hint = f"｜每班周课时需 ≤ {len(pairs)}"
            if teacher_count:
                hint += f"；教师并行容量 ≈ {capacity:g} 节（{teacher_count} 人 × {len(pairs)} 课位），需求 {demand:g} 节"
            if max_per_class.get(sid, 0) > len(pairs):
                hint += f"｜单班周课时 {max_per_class[sid]:g} 已超课位数"
        lines.append(f"- {name}：{len(d['classes'])} 个班 · 周课时合计 {d['periods']:g} · 教师 {teacher_count} 人 · {limit}{hint}")
    return "\n".join(lines)


async def lookup_slot_role_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None) -> str:
    """验算「课位需指定教师角色」（slot_teacher_role_required）硬规则是否必然无解。

    对每条启用的该类规则：课位数 = 每班需要由该角色教师上的节数；
    逐班对比该班班主任对本班的实际周课时（任教关系），并核对班主任并行数量。
    """
    from app.api.v1.scheduling import _load_rule_catalog

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"

    groups, _active = await _load_rule_catalog(session, tenant_id, year, term)
    rules = [
        r
        for g in groups
        for r in g.rules
        if r.enabled and r.priority == "hard" and r.code == "slot_teacher_role_required"
    ]
    if not rules:
        return f"{year}学年第{term}学期没有启用的「课位需指定教师角色」类规则。"

    classes = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.academic_year == year, Class.term == term,
    ))).scalars().all()
    if not classes:
        return "该学年学期还没有班级，无法验算。"

    assignments = (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == year, TeachingAssignment.term == term,
    ))).scalars().all()
    head_periods: dict[tuple[int, int], float] = {}
    for a in assignments:
        head_periods[(a.class_id, a.teacher_id)] = head_periods.get((a.class_id, a.teacher_id), 0) + float(a.weekly_periods or 0)
    user_rows = (await session.execute(select(User))).scalars().all()
    user_names = {u.id: u.name for u in user_rows}

    lines = [f"{year}学年第{term}学期「课位需指定教师角色」验算："]
    for rule in rules:
        days = list(rule.weekdays or [])
        periods = list(rule.periods or [])
        required = len(days) * len(periods)
        role_label = {"head_teacher": "班主任"}.get(rule.params.get("teacher_role", ""), "指定角色教师")
        scope_classes = classes
        if rule.target.type == "grade" and rule.target.ids:
            scope_classes = [c for c in classes if c.grade_id in rule.target.ids]
        elif rule.target.type == "class" and rule.target.ids:
            scope_classes = [c for c in classes if c.id in rule.target.ids]
        if not scope_classes:
            lines.append(f"- 规则「{rule.title}」：范围内没有班级，跳过。")
            continue

        shortages: list[str] = []
        heads: set[int] = set()
        for c in scope_classes:
            head_id = c.head_teacher_id
            if head_id is None:
                shortages.append(f"{c.name}（没有班主任）")
                continue
            heads.add(head_id)
            own = head_periods.get((c.id, head_id), 0)
            if own < required:
                shortages.append(f"{c.name} 班主任 {user_names.get(head_id, '?')} 对本班仅 {own:g} 节（差 {required - own:g}）")
        parallel_ok = len(heads) >= len(scope_classes)
        lines.append(
            f"- 规则「{rule.title}」：{_when(days, periods)} 共 {required} 个课位，"
            f"要求 {len(scope_classes)} 个班每班这 {required} 节全部由{role_label}上课"
            f"（并行需 {role_label} {len(scope_classes)} 人，实际 {len(heads)} 人，{'够' if parallel_ok else '不够'}）。"
        )
        if shortages:
            detail = "；".join(shortages[:_LIST_CAP])
            more = f"（其余 {len(shortages) - _LIST_CAP} 个班略）" if len(shortages) > _LIST_CAP else ""
            lines.append(f"  缺口：{detail}{more}")
        if not shortages and parallel_ok:
            lines.append("  每班班主任课时充足，该规则本身可满足。")

    return "\n".join(lines)


async def lookup_remaining_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, grade=None) -> str:
    """剩余课位容量：按班级对比课位结构容量与已排白天课时，附每科节数明细。

    只回数据，不做方案判断；加科/课时分配方案由模型基于数字给出。
    """
    from app.api.v1.scheduling import _load_grid_config

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"

    grid = await _load_grid_config(session, tenant_id, year, term)
    daily = [int(x or 0) for x in (grid.get("daily_periods") or [])[:7]]
    weekday_days = sum(1 for x in daily[:5] if x > 0)
    saturday = daily[5] if len(daily) > 5 else 0
    capacity = sum(daily)

    grade_id = None
    grade_rows = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    if grade:
        matched = next((g for g in grade_rows if grade in g.name), None)
        if matched is None:
            names = "、".join(g.name for g in grade_rows) or "暂无"
            return f"没有找到名称含「{grade}」的年级。现有年级：{names}。"
        grade_id = matched.id
    classes = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.academic_year == year, Class.term == term,
    ))).scalars().all()
    if grade_id is not None:
        classes = [c for c in classes if c.grade_id == grade_id]
    if not classes:
        return "该范围内还没有班级，无法统计剩余容量。请先完成班级划分。"
    class_ids = [c.id for c in classes]
    class_names = {c.id: c.name for c in classes}

    plans = (await session.execute(select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == year, CourseHourPlan.term == term,
        CourseHourPlan.class_id.in_(class_ids)))).scalars().all()
    subjects = {s.id: s.name for s in (await session.execute(select(Subject))).scalars().all()}

    per_class: dict[int, dict] = {cid: {"used": 0.0, "subjects": {}} for cid in class_ids}
    for p in plans:
        d = per_class.setdefault(p.class_id, {"used": 0.0, "subjects": {}})
        daytime = float(p.weekday_periods or 0) + float(p.saturday_periods or 0)
        d["used"] += daytime
        name = subjects.get(p.subject_id, f"科目{p.subject_id}")
        d["subjects"][name] = d["subjects"].get(name, 0) + daytime

    used_list = sorted(d["used"] for d in per_class.values())
    used_min, used_max = used_list[0], used_list[-1]
    grade_label = f"·{next((g.name for g in grade_rows if g.id == grade_id), grade)}" if grade_id is not None else "·全校"
    lines = [
        f"{year}学年第{term}学期{grade_label}，{len(class_ids)} 个班。",
        f"课位容量（白天）：{capacity} 节/班·周（{weekday_days} 个工作日各 {daily[0] if daily else 0} 节" + (f"，周六 {saturday} 节" if saturday else "") + "；晚自习课位另计）。",
        f"已排白天课时：最少 {used_min:g} / 最多 {used_max:g} 节 ⇒ 每班剩余 {capacity - used_max:g} ~ {capacity - used_min:g} 节。",
        "",
    ]
    for cid in sorted(per_class):
        d = per_class[cid]
        detail = " ".join(f"{name}{total:g}" for name, total in sorted(d["subjects"].items(), key=lambda kv: -kv[1]))
        lines.append(f"- {class_names[cid]}：已排 {d['used']:g}/{capacity} 节，剩 {capacity - d['used']:g} 节｜{detail or '未设科目'}")
    return "\n".join(lines)


async def lookup_generation_log(job_id: str, tenant_id: int) -> str:
    """读取生成长任务的求解事件日志（最近 40 条，含阶段/进度/消息），只读。"""
    import asyncio
    import time as _time
    from app.services.scheduling.generate_jobs import _redis, _job_key, get_job

    if not job_id:
        return "请先提供任务编号，或到排课页发起生成后再查询日志。"
    def snapshot():
        client = _redis()
        if client is not None:
            raw = client.get(_job_key(job_id))
            return json.loads(raw) if raw else None
        job = get_job(job_id)
        return job._snapshot() if job else None
    job = await asyncio.wait_for(asyncio.to_thread(snapshot), timeout=5)
    if not job or job.get("tenant_id") != tenant_id:
        return "本校未找到该生成任务的日志，任务可能已过期。请到排课页核对任务编号。"
    history = job.get("history") or []
    if not history:
        return "该任务还没有事件日志。"
    recent = history[-40:]
    lines = [f"生成任务日志（最近 {len(recent)} / 共 {len(history)} 条，状态：{job.get('status')}）："]
    for event in recent:
        ts = _time.strftime("%H:%M:%S", _time.localtime(event.get("ts") or _time.time()))
        stage = event.get("phase") or event.get("stage") or "-"
        percent = event.get("percent")
        pct = f" {percent}%" if isinstance(percent, (int, float)) and percent else ""
        message = (event.get("message") or "").strip()
        lines.append(f"[{ts}] {stage}{pct}：{message}" if message else f"[{ts}] {stage}{pct}")
    result = job.get("result")
    if result:
        lines.append(f"结果：已生成 {result.get('created', '?')} 节" + (f"，另有 {result.get('unplaced')} 节未排入" if result.get('unplaced') else ""))
    lines.append("以上为求解器事件原文；分析时结合 13-diagnose 的容量验算与 14-algorithm 的流程口径。")
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
        if name == "lookup_walk_classes":
            return await lookup_walk_classes(session, tenant_id, **scope,
                grade_id=args.get('grade_id') or (None if args.get('grade') else context.get('grade_id')),
                grade=args.get('grade'), subject=args.get('subject'))
        if name == "lookup_generation_status":
            result = await lookup_generation_status(str(args.get("job_id") or context.get("job_id") or ""), tenant_id)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "未找到" in result or "没有可核对" in result else "OK", scope=_tool_scope(args, page_context))
        if name == "lookup_teachers":
            result = await lookup_teachers(session, tenant_id, subject=str(args.get("subject") or ""), keyword=str(args.get("keyword") or ""), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有匹配" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_schedule_setup":
            result = await lookup_schedule_setup(session, tenant_id, class_id=args.get("class_id") or context.get("class_id"), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没设置" in result or "未找到指定班级" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_rules":
            result = await lookup_rules(session, tenant_id, rule_group_id=args.get("rule_group_id") or context.get("rule_group_id"), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有规则组" in result or "未找到所选规则组" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_subject_capacity":
            result = await lookup_subject_capacity(session, tenant_id, grade=str(args.get("grade") or ""), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有班级" in result or "没有找到名称含" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_remaining_capacity":
            result = await lookup_remaining_capacity(session, tenant_id, grade=str(args.get("grade") or ""), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有班级" in result or "没有找到名称含" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_generation_log":
            result = await lookup_generation_log(str(args.get("job_id") or context.get("job_id") or ""), tenant_id)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "未找到" in result or "请先提供" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_slot_role_capacity":
            result = await lookup_slot_role_capacity(session, tenant_id, **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有启用" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_playbook":
            result = lookup_playbook(arguments)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有对上" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        names = ", ".join(t["function"]["name"] for t in SCHOOL_TOOLS)
        return _tool_response(name, ok=False, code="INVALID_ARGUMENT", message=f"没有名为「{name}」的工具。可用工具：{names}")

    try:
        return await dispatch()
    except (TimeoutError, ConnectionError) as exc:
        logger.warning("assistant.tool transient_retry name=%s error=%s", name, type(exc).__name__)
        try:
            await asyncio.sleep(0.2)
            return await dispatch()
        except Exception:
            logger.exception("assistant.tool retry_fail name=%s", name)
            return _tool_response(name, ok=False, code="TOOL_UNAVAILABLE", message=f"工具 {name} 暂时无法连接。请稍后重试，或让老师自己到对应页面核对。", retryable=True)
    except Exception:
        logger.exception("assistant.tool fail name=%s args=%s", name, (arguments or "")[:120])
        return _tool_response(name, ok=False, code="INTERNAL_ERROR", message=f"工具 {name} 查询失败。请换个问法，或让老师自己到对应页面核对。")


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
