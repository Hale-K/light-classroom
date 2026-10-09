"""容量验算职责：科目容量、课位角色规则验算、剩余课位三个只读验算工具。"""
from __future__ import annotations

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Class, CourseHourPlan, Grade, Subject, TeachingAssignment, User
from app.ai.tools.school.common import _LIST_CAP, _term, _when

TOOLS: list[dict] = [
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
]


# Every capacity query exposes the same explicit historical/grade scope to the model.
for _definition in TOOLS:
    _definition['function']['parameters']['properties'].update({
        'academic_year': {'type': 'string', 'minLength': 4, 'maxLength': 20},
        'term': {'type': 'string', 'enum': ['1', '2']},
        'grade_id': {'type': 'integer', 'minimum': 1, 'description': '已核实本校年级ID；不同年级使用各自课位结构'},
    })


async def lookup_subject_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, grade=None, grade_id=None) -> str:
    """容量验算数据：按年级聚合各科 班级数/周课时/教师数 + 硬性学科限排课位。

    供模型判断「某科课时需求能否排进限排课位」：限排课位数 < 该科每班周课时，
    或 教师并行容量（课位数 × 教师数）< 周课时合计 ⇒ 必然无解。
    """
    from app.api.v1.scheduling import _load_rule_catalog
    from app.services.scheduling.rules import generation_subject_allowed_slots

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"

    grade_rows = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    if grade or grade_id is not None:
        matched = [g for g in grade_rows if (not grade or grade in g.name) and (grade_id is None or g.id == grade_id)]
        if len(matched) != 1:
            names = "、".join(g.name for g in grade_rows) or "暂无"
            return f"没有找到名称含「{grade or grade_id}」的唯一年级。现有年级：{names}。"
        grade_id = matched[0].id
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
    subjects = {s.id: s.name for s in (await session.execute(select(Subject).where(
        (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None)))).scalars().all()}

    from app.api.v1.scheduling import _load_grid_config
    from app.services.scheduling.grid_slots import allowed_slots
    from app.services.scheduling.rules import pick_rule_group
    groups, active_id = await _load_rule_catalog(session, tenant_id, year, term)
    scope_label = f"·{next((g.name for g in grade_rows if g.id == grade_id), grade or '')}" if grade_id is not None else "·全校"
    lines = [f"{year}学年第{term}学期{scope_label}，共 {len(class_ids)} 个班。各科目容量验算："]
    for gid in sorted({c.grade_id for c in classes}):
        grid = await _load_grid_config(session, tenant_id, year, term, grade_id=gid)
        grade_name = next((g.name for g in grade_rows if g.id == gid), str(gid))
        if not grid['configured']:
            lines.append(f'{grade_name}课位结构尚未保存，不能核实科目容量。')
            continue
        actual = allowed_slots(grid, 'daytime')
        group = pick_rule_group([g for g in groups if g.grade_id in (None, gid)], grade_id=gid, active_id=active_id)
        restricted = generation_subject_allowed_slots(group) if group else {}
        ids = {c.id for c in classes if c.grade_id == gid}
        scoped_plans = [p for p in plans if p.class_id in ids]
        for sid in sorted({p.subject_id for p in scoped_plans}):
            teachers = {a.teacher_id for a in assignments if a.class_id in ids and a.subject_id == sid and a.teacher_id is not None}
            for parity, label in (('odd', '单周'), ('even', '双周')):
                applicable = [p for p in scoped_plans if p.subject_id == sid and p.week_parity in ('all', parity)]
                demand = sum(p.weekday_periods + p.saturday_periods for p in applicable)
                available = actual[parity] & restricted[sid] if sid in restricted else actual[parity]
                parallel = len(available) * len(teachers)
                lines.append(f"- {grade_name}·{subjects.get(sid, '未知科目')}{label}：{len({p.class_id for p in applicable})} 个班，配置白天需求 {demand:g} 节；实际允许课位 {len(available)} 个；任课教师 {len(teachers)} 人，理论并行容量上限 {parallel} 节。")
    lines.append('配置课时与已排课表分开；这里只给容量必要条件，晚课、教师禁排及跨年级占用另查，不能判定整体可行。')
    return "\n".join(lines)


async def lookup_slot_role_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, grade_id=None) -> str:
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
    if grade_id is not None:
        classes = [item for item in classes if item.grade_id == grade_id]
    if not classes:
        return "该学年学期还没有班级，无法验算。"

    assignments = (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == year, TeachingAssignment.term == term,
    ))).scalars().all()
    head_periods: dict[tuple[int, int], float] = {}
    for a in assignments:
        head_periods[(a.class_id, a.teacher_id)] = head_periods.get((a.class_id, a.teacher_id), 0) + float(a.weekly_periods or 0)
    user_rows = (await session.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all()
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


async def lookup_remaining_capacity(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, grade=None, grade_id=None) -> str:
    """剩余课位容量：按班级对比课位结构容量与已排白天课时，附每科节数明细。

    只回数据，不做方案判断；加科/课时分配方案由模型基于数字给出。
    """
    from app.api.v1.scheduling import _load_grid_config
    from app.services.scheduling.grid_slots import allowed_slots

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"

    grade_rows = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    if grade or grade_id is not None:
        matched = [g for g in grade_rows if (not grade or grade in g.name) and (grade_id is None or g.id == grade_id)]
        if len(matched) != 1:
            names = "、".join(g.name for g in grade_rows) or "暂无"
            return f"没有找到名称含「{grade or grade_id}」的唯一年级。现有年级：{names}。"
        grade_id = matched[0].id
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
    subjects = {s.id: s.name for s in (await session.execute(select(Subject).where(
        (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None)))).scalars().all()}
    grids = {gid: await _load_grid_config(session, tenant_id, year, term, grade_id=gid)
             for gid in sorted({c.grade_id for c in classes})}
    grade_label = f"·{next((g.name for g in grade_rows if g.id == grade_id), grade)}" if grade_id is not None else "·全校"
    lines = [f"{year}学年第{term}学期{grade_label}，{len(class_ids)} 个班；以下为配置课时，不是已排课表。"]
    for c in classes:
        grid = grids[c.grade_id]
        if not grid['configured']:
            lines.append(f"- {class_names[c.id]}：年级课位结构未保存，无法核实剩余容量。")
            continue
        actual = allowed_slots(grid, 'daytime')
        for parity, label in (('odd', '单周'), ('even', '双周')):
            applicable = [p for p in plans if p.class_id == c.id and p.week_parity in ('all', parity)]
            used = sum(p.weekday_periods + p.saturday_periods for p in applicable)
            capacity = len(actual[parity])
            detail = '、'.join(f"{subjects.get(p.subject_id, '未知科目')}{p.weekday_periods + p.saturday_periods:g}" for p in applicable)
            lines.append(f"- {c.name}{label}：配置 {used:g}/{capacity} 节，剩 {capacity - used:g} 节；工作日课位 {sum(day <= 5 for day, _ in actual[parity])}，周末课位 {sum(day >= 6 for day, _ in actual[parity])}｜{detail or '未设科目'}")
    lines.append('仅核对课量与实际课位；晚课另计，未验证全部约束或走班联合可行性。')
    return "\n".join(lines)
