"""准备度职责：学年学期的排课准备概况（网格/班级/课时/任教/规则组）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Class, CourseHourPlan, Subject, TeachingAssignment
from app.ai.tools.school.common import _term

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_schedule_setup",
            "description": "只读检查本校指定学年学期的排课准备度，返回课位网格、班级、课时方案、任教覆盖和规则组概况。准备度不等于一定可排且不保证无冲突。",
            "parameters": {
                "type": "object",
                "properties": {
                    "academic_year": {"type": "string", "description": "查询学年；默认当前页面学年，否则本校当前学年"},
                    "term": {"type": "string", "description": "查询学期"},
                    "class_id": {"type": "integer", "description": "只查询一个班时填写页面或查询确认的班级ID；不填查全校"},
                    'grade_id': {'type': 'integer', 'minimum': 1, 'description': '查询指定年级的独立课位结构'},
                    'grade': {'type': 'string', 'description': '明确年级名称；重名时需ID'},
                },
                "additionalProperties": False,
            },
        },
    },
]


async def lookup_schedule_setup(session: AsyncSession, tenant_id: int, *, academic_year=None, term=None, class_id=None, grade_id=None, grade=None) -> str:
    from app.api.v1.scheduling import _load_grid_config, _load_rule_catalog
    from app.ai.tools.readiness import readiness_lines

    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    if not year:
        return "本校还没设置当前学年。请先到系统设置核对学年学期。"
    from app.models.org import Grade
    from app.services.scheduling.grid_slots import allowed_slots
    if grade or grade_id is not None:
        grades = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
        matches = [item for item in grades if (grade_id is None or item.id == grade_id) and (not grade or grade in item.name)]
        if len(matches) != 1:
            return '未找到指定班级或唯一年级，请确认学年学期与年级。'
        grade_id = matches[0].id
    stmt = select(Class).where(Class.tenant_id == tenant_id, Class.academic_year == year, Class.term == term)
    if class_id is not None:
        stmt = stmt.where(Class.id == int(class_id))
    if grade_id is not None:
        stmt = stmt.where(Class.grade_id == grade_id)
    classes = (await session.execute(stmt)).scalars().all()
    if class_id is not None and not classes:
        return "本校未找到指定班级，请重新选择班级。"
    plans = (await session.execute(select(CourseHourPlan).where(CourseHourPlan.tenant_id == tenant_id, CourseHourPlan.academic_year == year, CourseHourPlan.term == term))).scalars().all()
    assignments = (await session.execute(select(TeachingAssignment).where(TeachingAssignment.tenant_id == tenant_id, TeachingAssignment.academic_year == year, TeachingAssignment.term == term))).scalars().all()
    subjects = (await session.execute(select(Subject.__table__).where((Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None)))).all()
    groups, active_id = await _load_rule_catalog(session, tenant_id, year, term)
    active = next((g.name for g in groups if g.id == active_id), "未选择")
    lines = [f"{year}学年第{term}学期。"]
    for gid in sorted({item.grade_id for item in classes}):
        scoped_classes = [item for item in classes if item.grade_id == gid]
        grid = await _load_grid_config(session, tenant_id, year, term, grade_id=gid)
        lines.append(f'年级ID {gid}（独立年级课位）：')
        if not grid['configured']:
            lines.extend(readiness_lines(scoped_classes, plans, assignments, subjects, grid))
            continue
        for parity, label in (('odd', '单周'), ('even', '双周')):
            actual = allowed_slots(grid, 'daytime')[parity]
            parity_grid = {**grid, 'daily_periods': [sum(day == weekday for day, _ in actual) for weekday in range(1, 8)]}
            parity_plans = [p for p in plans if p.week_parity in ('all', parity)]
            lines.append(f'{label}：')
            lines.extend(readiness_lines(scoped_classes, parity_plans, assignments, subjects, parity_grid))
    if not classes:
        lines.append('该学年学期范围内没有行政班。')
    lines.append(f"规则组共 {len(groups)} 个，当前启用：{active}。" + ("请先到规则组建立适用年级的规则。" if not groups else ""))
    lines.append('课位具体节次与规划依据用 lookup_planning_basis 核对；准备度不代表可行性。')
    return '\n'.join(lines)
