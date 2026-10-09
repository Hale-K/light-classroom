"""走班职责：已保存走班教学班的核对（班数/班额/入班/任课/已排课节）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Grade, Subject, User
from app.ai.tools.school.common import _term, _tool_response

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_walk_classes",
            "description": "只读核对已保存走班教学班：班数、班额、实际入班人数、固定任课教师、配置课时、已排课节、课表教师是否与任课关系一致；按同科教师汇总课时和人数。必须明确年级，不重分班、不改教师、不重新排课。人数为零可能是尚未入班，不代表生成失败；结果不包含未保存预览。",
            "parameters": {"type": "object", "properties": {
                "academic_year": {"type": "string"}, "term": {"type": "string", "enum": ["1", "2"]},
                "grade_id": {"type": "integer", "description": "已确认的年级ID；默认当前页面年级"},
                "grade": {"type": "string", "description": "未知道ID时提供年级名称，如高一"},
                "subject": {"type": "string", "description": "科目名称；省略查询该年级全部走班科目"},
            }, "additionalProperties": False},
        },
    },
]


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
