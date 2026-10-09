"""保存数据的只读证据：选科、任课、合并课表与资源碰撞。"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.models.org import (
    Class, CourseHourPlan, Grade, Schedule, Student, StudentClassMembership,
    StudentGradeMembership, Subject, TeachingAssignment, User,
)
from app.models.gaokao import (
    StudentSubjectChoice, TeachingClass, TeachingClassSchedule, TeachingClassStudent,
)
from app.ai.tools.school.common import _term, _tool_response
from app.ai.tools.school.context import timetable_mode


class ModeMismatch(ValueError):
    pass


class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')
    academic_year: str | None = Field(default=None, min_length=1, max_length=20)
    term: Literal['1', '2'] | None = None
    grade_id: int | None = Field(default=None, gt=0, strict=True)
    grade: str | None = Field(default=None, min_length=1, max_length=50)
    class_id: int | None = Field(default=None, gt=0, strict=True)
    class_name: str | None = Field(default=None, min_length=1, max_length=50, description='行政班完整名称；重名时需提供年级或ID')
    teacher_id: int | None = Field(default=None, gt=0, strict=True)
    teacher: str | None = Field(default=None, min_length=1, max_length=50, description='教师完整姓名；重名时需提供ID')
    student_id: int | None = Field(default=None, gt=0, strict=True)
    student: str | None = Field(default=None, min_length=1, max_length=50, description='学生完整姓名或学号；重名时需提供ID')
    subject: str | None = Field(default=None, min_length=1, max_length=20)
    weekday: int | None = Field(default=None, ge=1, le=7, strict=True)
    period: int | None = Field(default=None, ge=1, le=30, strict=True)
    lesson_type: Literal['auto', 'administrative', 'walk', 'combined'] = Field(default='auto',
        description='课程类型，不是学校模式：auto按学校模式查询；行政模式仅行政课，走班模式默认合并，也可单查administrative或walk。选科查询不使用此参数。')
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=50, ge=1, le=100, strict=True)


DESCRIPTIONS = {
    'lookup_student_choices': '只读查询指定年级学期的学生选科、行政班归属和已保存教学班入班；区分未选科、草稿、确认和锁定状态，汇总选科及未入班人数。学生归属使用学年/学期快照，不用当前班级推断历史。缺少快照会明确说明，不能判定生成失败。',
    'lookup_teaching_assignments': '只读查询行政班与走班固定任课明细和教师配置工作量；行政班课时方案按每周/单周/双周分别展示，任课记录课时与方案分别展示，不自动合并或修改。比较已保存课表教师与固定任课是否一致，不推断谁修改过数据。',
    'lookup_timetable': '只读查询已保存行政课和走班课的合并课表，支持学生个人课表、教师、行政班、科目、星期节次筛选。保留单双周与来源，配置课时不等于已排节数。分页返回 total、has_more、next_offset；需要完整列表时继续取下一页，不含预览。',
    'lookup_schedule_conflicts': '只读核对保存课表的教师、学生、班级和教室同一时段碰撞，按单双周分别核对；跨行政课、走班课和年级查共享资源。筛选范围不会排除与之冲突的其他课。教室按存储名称匹配，仅为候选冲突；缺名单会报告，未发现碰撞不代表全部规则满足或求解可行。',
}
TOOLS = [
    {'type': 'function', 'function': {
        'name': name, 'description': description,
        'parameters': Query.model_json_schema(),
    }}
    for name, description in DESCRIPTIONS.items()
]


async def authorized(session, tenant_id, user_id):
    """学校级查询沿用教务管理权限，不能由页面或规则写权限代替身份。"""
    from app.models.rbac import Role, UserRole

    if user_id is None:
        return False
    users = await _rows(session, User, User.id == user_id, User.tenant_id == tenant_id,
                        User.status == 'active', User.frozen.is_(False))
    if not users:
        return False
    if users[0].role == 'director':
        return True
    if users[0].role != 'teacher':
        return False
    roles = (await session.execute(select(Role.code).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.code == 'academic_director',
               (Role.tenant_id == tenant_id) | Role.tenant_id.is_(None)))).scalars().all()
    return bool(roles)


async def _rows(session, model, *conditions):
    return list((await session.execute(select(model).where(*conditions))).scalars().all())


@dataclass
class Evidence:
    query: Query
    scope: dict
    classes: dict
    walks: dict
    students: dict
    members: dict
    admin_members: dict
    grade_students: set
    subjects: dict
    teachers: dict
    lessons: list
    missing: dict

    def matches(self, item):
        q = self.query
        if q.lesson_type in ('administrative', 'walk') and item['kind'] != q.lesson_type:
            return False
        if item['grade_id'] != self.scope['grade_id']:
            return False
        if q.class_id is not None:
            if item['kind'] == 'administrative' and item['class_id'] != q.class_id:
                return False
            if item['kind'] == 'walk' and not (
                self.members.get(item['class_id'], set()) & self.admin_members.get(q.class_id, set())
            ):
                return False
        if q.teacher_id is not None and item['teacher_id'] != q.teacher_id:
            return False
        if q.student_id is not None and q.student_id not in self.lesson_students(item):
            return False
        return all(value is None or item[key] == value for key, value in (
            ('subject', q.subject.strip() if q.subject else None),
            ('weekday', q.weekday), ('period', q.period),
        ))

    def lesson_students(self, item):
        groups = self.admin_members if item['kind'] == 'administrative' else self.members
        return groups.get(item['class_id'], set())


async def _load(session, tenant_id, q):
    if not q.academic_year or not q.term:
        year, term = await _term(session, tenant_id)
        q = q.model_copy(update={'academic_year': q.academic_year or year, 'term': q.term or term})
    if not q.academic_year or q.term not in ('1', '2'):
        raise ValueError('请明确学年学期，学校当前学期尚未配置。')
    mode = await timetable_mode(session, tenant_id)
    if mode == 'administrative' and q.lesson_type in ('walk', 'combined'):
        raise ModeMismatch('学校当前为行政班课表模式，只核对行政课；若要核对历史走班数据，请先明确模式与历史范围。')
    if q.lesson_type == 'auto':
        q = q.model_copy(update={'lesson_type': 'administrative' if mode == 'administrative' else 'combined'})
    grades = await _rows(session, Grade, Grade.tenant_id == tenant_id)
    classes = {c.id: c for c in await _rows(session, Class, Class.tenant_id == tenant_id,
        Class.academic_year == q.academic_year, Class.term == q.term)}
    if q.class_name:
        matches = [c for c in classes.values() if c.name == q.class_name.strip()
            and (q.class_id is None or c.id == q.class_id)
            and (q.grade_id is None or c.grade_id == q.grade_id)
            and (not q.grade or any(g.id == c.grade_id and q.grade.strip() in g.name for g in grades))]
        if len(matches) != 1:
            raise ValueError('该学期班级名称未唯一匹配，请确认完整名称、年级或班级ID。')
        q = q.model_copy(update={'class_id': matches[0].id})
    if q.class_id is not None and q.class_id not in classes:
        raise ValueError('未找到本校该学期的行政班，请确认班级和学年学期。')
    matches = [g for g in grades if (
        (q.grade_id is None or g.id == q.grade_id)
        and (not q.grade or q.grade.strip() in g.name)
        and (q.class_id is None or g.id == classes[q.class_id].grade_id)
    )]
    if (q.grade_id is None and not q.grade and q.class_id is None) or len(matches) != 1:
        raise ValueError('请明确要查询的年级；名称匹配多个年级时请提供具体年级。')
    grade = matches[0]
    q = q.model_copy(update={'grade_id': grade.id})
    scope = q.model_dump(exclude_none=True, exclude={'offset', 'limit'})
    scope['grade'] = grade.name
    scope.update({'timetable_mode': mode, 'mode_source': 'school_current_setting',
                  'historical_mode_verified': False})
    walks = {c.id: c for c in await _rows(session, TeachingClass, TeachingClass.tenant_id == tenant_id,
        TeachingClass.academic_year == q.academic_year, TeachingClass.term == q.term)} if mode == 'walk_class' else {}
    students = {s.id: s for s in await _rows(session, Student, Student.tenant_id == tenant_id)}
    memberships = await _rows(session, StudentClassMembership,
        StudentClassMembership.tenant_id == tenant_id,
        StudentClassMembership.academic_year == q.academic_year,
        StudentClassMembership.term == q.term, StudentClassMembership.status == 'active')
    admin_members = defaultdict(set)
    for m in memberships:
        if m.class_id in classes and m.student_id in students and m.grade_id == classes[m.class_id].grade_id:
            admin_members[m.class_id].add(m.student_id)
    grade_memberships = await _rows(session, StudentGradeMembership,
        StudentGradeMembership.tenant_id == tenant_id,
        StudentGradeMembership.academic_year == q.academic_year,
        StudentGradeMembership.grade_id == grade.id, StudentGradeMembership.status == 'active')
    grade_students = {m.student_id for m in grade_memberships if m.student_id in students}
    for cid, members in admin_members.items():
        if classes[cid].grade_id == grade.id:
            grade_students.update(members)
    walk_members = await _rows(session, TeachingClassStudent, TeachingClassStudent.tenant_id == tenant_id,
        TeachingClassStudent.teaching_class_id.in_(walks)) if walks else []
    members = defaultdict(set)
    invalid_member_count = 0
    for m in walk_members:
        if m.student_id in students:
            members[m.teaching_class_id].add(m.student_id)
            if walks[m.teaching_class_id].grade_id == grade.id:
                grade_students.add(m.student_id)
        else:
            invalid_member_count += 1
    subjects = {s.id: s.name for s in await _rows(session, Subject,
        (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None))}
    teachers = {t.id: t.name for t in await _rows(session, User, User.tenant_id == tenant_id)}
    for field, text, source in (
        ('teacher_id', q.teacher, [(tid, name) for tid, name in teachers.items()]),
        ('student_id', q.student, [(sid, s.name) for sid, s in students.items() if sid in grade_students]
            + [(sid, s.student_no) for sid, s in students.items() if sid in grade_students]),
    ):
        if not text:
            continue
        matched_ids = {sid for sid, label in source if label == text.strip()
                       and (getattr(q, field) is None or sid == getattr(q, field))}
        if len(matched_ids) != 1:
            raise ValueError('教师或学生姓名未唯一匹配，请提供完整姓名、学生学号或具体ID。')
        q = q.model_copy(update={field: matched_ids.pop()})
    scope.update(q.model_dump(exclude_none=True, exclude={'offset', 'limit', 'grade'}))
    lessons = []
    orphan_schedules = 0
    for model, groups, kind, fk in (
        (Schedule, classes, 'administrative', 'class_id'),
        (TeachingClassSchedule, walks, 'walk', 'teaching_class_id'),
    ):
        if kind == 'walk' and mode == 'administrative':
            continue
        rows = await _rows(session, model, model.tenant_id == tenant_id,
            model.academic_year == q.academic_year, model.term == q.term)
        for s in rows:
            cid = getattr(s, fk)
            if cid not in groups:
                orphan_schedules += 1
                continue
            c = groups[cid]
            lessons.append({'kind': kind, 'schedule_id': s.id, 'class_id': cid,
                'class_name': c.name, 'grade_id': c.grade_id,
                'subject_id': s.subject_id, 'subject': subjects.get(s.subject_id),
                'teacher_id': s.teacher_id, 'teacher_name': teachers.get(s.teacher_id),
                'weekday': s.weekday, 'period': s.period, 'room': s.room,
                'week_parity': getattr(getattr(s, 'week_parity', 'all'), 'value', getattr(s, 'week_parity', 'all'))})
    lessons.sort(key=lambda s: (s['weekday'], s['period'], s['kind'], s['class_id'], s['schedule_id']))
    all_admin_students = set().union(*admin_members.values()) if admin_members else set()
    missing = {
        'administrative_classes_without_members': [c.id for c in classes.values()
            if c.grade_id == grade.id and not admin_members[c.id]],
        'teaching_classes_without_members': [c.id for c in walks.values()
            if c.grade_id == grade.id and not members[c.id]],
        'students_without_term_class': sorted(grade_students - all_admin_students),
        'invalid_teaching_class_member_count': invalid_member_count,
        'orphan_schedule_count_in_school_term': orphan_schedules,
        'population_basis': '学年年级快照、学期行政班归属和已保存教学班成员；不使用学生当前年级或旧班级补历史。缺少全部关联的学生无法统计。',
        'walk_enrollment_applicable': mode == 'walk_class',
    }
    for key, value in list(missing.items()):
        if isinstance(value, list):
            missing[key + '_count'] = len(value)
            missing[key + '_truncated'] = len(value) > 100
            missing[key] = value[:100]
    return Evidence(q, scope, classes, walks, students, members, admin_members,
                    grade_students, subjects, teachers, lessons, missing)


def _page(items, q):
    end = q.offset + q.limit
    return {'total': len(items), 'items': items[q.offset:end], 'offset': q.offset,
            'limit': q.limit, 'has_more': end < len(items),
            'next_offset': end if end < len(items) else None}


async def _choices(session, tenant_id, e):
    q = e.query
    choices = {c.student_id: c for c in await _rows(session, StudentSubjectChoice,
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.academic_year == q.academic_year,
        StudentSubjectChoice.effective_term == q.term)}
    admins_by_student, walks_by_student = defaultdict(list), defaultdict(list)
    for cid, people in e.admin_members.items():
        for sid in people:
            admins_by_student[sid].append(cid)
    for cid, people in e.members.items():
        if e.walks[cid].grade_id == q.grade_id:
            for sid in people:
                walks_by_student[sid].append(cid)
    teacher_classes = set()
    if q.teacher_id is not None:
        teacher_classes = {a.class_id for a in await _rows(session, TeachingAssignment,
            TeachingAssignment.tenant_id == tenant_id, TeachingAssignment.academic_year == q.academic_year,
            TeachingAssignment.term == q.term, TeachingAssignment.teacher_id == q.teacher_id)}
    items, counts = [], defaultdict(lambda: {
        'selected_students': 0, 'not_enrolled_students': 0, 'choice_status_counts': Counter(),
    })
    for sid in sorted(e.grade_students):
        if q.student_id is not None and sid != q.student_id:
            continue
        admins = sorted(admins_by_student[sid])
        enrolled = sorted(walks_by_student[sid])
        if q.class_id is not None and q.class_id not in admins:
            continue
        if q.teacher_id is not None and not (teacher_classes.intersection(admins) or
            any(e.walks[cid].teacher_id == q.teacher_id for cid in enrolled)):
            continue
        choice = choices.get(sid)
        selected = sorted(set(choice.selected_subject_ids or (
            ([choice.primary_subject_id] if choice.primary_subject_id else []) + choice.secondary_subject_ids
        ))) if choice else []
        if q.subject and not any(e.subjects.get(s) == q.subject.strip() for s in selected):
            continue
        for subject_id in selected:
            counts[subject_id]['selected_students'] += 1
            counts[subject_id]['choice_status_counts'][choice.status] += 1
            if e.scope['timetable_mode'] == 'walk_class' and not any(e.walks[cid].subject_id == subject_id for cid in enrolled):
                counts[subject_id]['not_enrolled_students'] += 1
        items.append({'student_id': sid, 'student_name': e.students[sid].name,
            'administrative_class_ids': admins, 'teaching_class_ids': enrolled,
            'choice_status': choice.status if choice else 'missing',
            'selected_subject_ids': selected, 'subjects': [e.subjects.get(s) for s in selected],
            'stream': choice.stream if choice else None,
            'duplicate_subject_enrollments': [subject_id for subject_id, n in
                Counter(e.walks[cid].subject_id for cid in enrolled).items() if n > 1]})
    return {**_page(items, q), 'missing_choice_count': sum(i['choice_status'] == 'missing' for i in items),
        'choice_status_counts': dict(Counter(i['choice_status'] for i in items)),
        'subjects': [{'subject_id': sid, 'subject': e.subjects.get(sid), **value}
            for sid, value in sorted(counts.items())], 'missing_data': e.missing}


async def _assignments(session, tenant_id, e):
    q = e.query
    assignments = await _rows(session, TeachingAssignment, TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == q.academic_year, TeachingAssignment.term == q.term)
    plans = await _rows(session, CourseHourPlan, CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == q.academic_year, CourseHourPlan.term == q.term)
    admin = {(a.class_id, a.subject_id): a for a in assignments if a.class_id in e.classes}
    plan_groups = defaultdict(list)
    for p in plans:
        if p.class_id in e.classes:
            plan_groups[(p.class_id, p.subject_id)].append(p)
    items = []
    slots_by_class_subject = defaultdict(list)
    for slot in e.lessons:
        slots_by_class_subject[(slot['kind'], slot['class_id'], slot['subject_id'])].append(slot)
    for kind, cid, subject_id in (
        [('administrative', *key) for key in sorted(admin.keys() | plan_groups.keys())]
        + [('walk', cid, c.subject_id) for cid, c in sorted(e.walks.items())]
    ):
        c = e.classes[cid] if kind == 'administrative' else e.walks[cid]
        a = admin.get((cid, subject_id)) if kind == 'administrative' else c
        item = {'kind': kind, 'class_id': cid, 'class_name': c.name, 'grade_id': c.grade_id,
                'subject_id': subject_id, 'subject': e.subjects.get(subject_id),
                'teacher_id': a.teacher_id if a else None,
                'teacher_name': e.teachers.get(a.teacher_id) if a else None}
        # 星期/节次只用于课表与冲突查询，任课数据没有时段。
        if not e.matches({**item, 'weekday': q.weekday, 'period': q.period}):
            continue
        slots = slots_by_class_subject[(kind, cid, subject_id)]
        item.update({'assignment_weekly_periods': a.weekly_periods if a else None,
            'assignment_missing': a is None or a.teacher_id is None,
            'student_count': len(e.lesson_students(item)),
            'scheduled_periods': len(slots),
            'scheduled_periods_by_week': {parity: sum(s['week_parity'] in ('all', parity) for s in slots)
                for parity in ('odd', 'even')},
            'scheduled_teacher_mismatch_count': sum(s['teacher_id'] != item['teacher_id'] for s in slots),
            'hour_plans': [{'week_parity': p.week_parity.value, 'weekly_periods': p.weekly_periods,
                'weekday_periods': p.weekday_periods, 'saturday_periods': p.saturday_periods,
                'evening_periods_odd': p.evening_periods_odd,
                'evening_periods_even': p.evening_periods_even}
                for p in sorted(plan_groups[(cid, subject_id)], key=lambda p: str(p.week_parity))]
                if kind == 'administrative' else [],
        })
        items.append(item)
    loads = {}
    for item in items:
        tid = item['teacher_id']
        if tid is None:
            continue
        load = loads.setdefault(tid, {'teacher_id': tid, 'teacher_name': e.teachers.get(tid),
            'administrative_assignment_periods': 0, 'walk_configured_periods': 0,
            'scheduled_periods_by_week': {'odd': 0, 'even': 0}})
        field = 'administrative_assignment_periods' if item['kind'] == 'administrative' else 'walk_configured_periods'
        load[field] += item['assignment_weekly_periods'] or 0
    matched_keys = {(item['kind'], item['class_id'], item['subject_id']) for item in items}
    for slot in e.lessons:
        tid = slot['teacher_id']
        if (slot['kind'], slot['class_id'], slot['subject_id']) not in matched_keys or tid is None:
            continue
        load = loads.setdefault(tid, {'teacher_id': tid, 'teacher_name': e.teachers.get(tid),
            'administrative_assignment_periods': 0, 'walk_configured_periods': 0,
            'scheduled_periods_by_week': {'odd': 0, 'even': 0}})
        for parity in ('odd', 'even'):
            if slot['week_parity'] in ('all', parity):
                load['scheduled_periods_by_week'][parity] += 1
    return {**_page(items, q), 'teachers': list(loads.values())[:100],
            'teacher_count': len(loads), 'teachers_truncated': len(loads) > 100, 'missing_data': e.missing,
            'workload_basis': '仅当前查询范围；任课记录课时、课时方案、已排节数分别展示，不等同。'}


def _conflicts(e):
    anchors = {(s['kind'], s['schedule_id']) for s in e.lessons if e.matches(s)}
    groups = defaultdict(list)

    def resource_keys(s):
        resources = [('class', f"{s['kind']}:{s['class_id']}")]
        if s['teacher_id'] is not None:
            resources.append(('teacher', s['teacher_id']))
        if s['room'] and s['room'].strip():
            resources.append(('room', s['room'].strip()))
        resources.extend(('student', sid) for sid in e.lesson_students(s))
        for parity in ('odd', 'even'):
            if s['week_parity'] not in ('all', parity):
                continue
            for kind, resource in resources:
                yield (kind, resource, s['weekday'], s['period'], parity)

    # 只建立查询目标涉及的资源时段，但保留全校其他年级的竞争课节。
    relevant_keys = {key for s in e.lessons if (s['kind'], s['schedule_id']) in anchors
                     for key in resource_keys(s)}
    for s in e.lessons:
        for key in resource_keys(s):
            if key in relevant_keys:
                groups[key].append(s)
    items = []
    for (kind, resource, weekday, period, parity), slots in groups.items():
        if len(slots) < 2 or not any((s['kind'], s['schedule_id']) in anchors for s in slots):
            continue
        items.append({'resource_type': kind, 'resource_id': resource, 'weekday': weekday,
            'period': period, 'week_parity': parity, 'lessons': slots,
            'candidate_only': kind == 'room'})
    items.sort(key=lambda i: (i['weekday'], i['period'], i['week_parity'], i['resource_type'], str(i['resource_id'])))
    return {**_page(items, e.query), 'counts_by_resource': dict(Counter(i['resource_type'] for i in items)),
        'coverage': {'includes_cross_grade_resources': True, 'full_rule_validation': False,
            'student_basis': '该学期行政班归属与已保存教学班成员；缺少名单的学生冲突无法核验。',
            'room_basis': '仅按保存的教室名称匹配；同名异校区、别名和空教室未核实。',
            'saved_only': True, 'checked_anchor_lessons': len(anchors)},
        'missing_data': e.missing}


async def execute(name, arguments, *, session, tenant_id, page_context):
    try:
        raw = json.loads(arguments or '{}')
        if not isinstance(raw, dict):
            raise ValueError('参数必须为对象')
        # 用户显式换年级/班级时不继承页面上的其他班级选择。
        context = page_context or {}
        values = dict(raw)
        for key in ('academic_year', 'term'):
            if key not in values and context.get(key) is not None:
                values[key] = context[key]
        if not any(key in values for key in ('grade_id', 'grade', 'class_id', 'class_name')):
            for key in ('grade_id', 'class_id'):
                if context.get(key) is not None:
                    values[key] = context[key]
        q = Query.model_validate(values)
        if name == 'lookup_student_choices' and q.lesson_type != 'auto':
            raise ValueError('选科查询不按课表课程类型筛选。')
        if name in ('lookup_student_choices', 'lookup_teaching_assignments') and (q.weekday or q.period):
            raise ValueError('选科和任课查询不支持星期节次筛选，请使用课表查询。')
    except (ValueError, ValidationError):
        return _tool_response(name, ok=False, code='INVALID_ARGUMENT',
            message='查询参数无效，请使用有效的整数ID、学期1或2和分页范围；选科与任课不支持星期节次。')
    try:
        e = await _load(session, tenant_id, q)
    except ModeMismatch as exc:
        return _tool_response(name, ok=False, code='MODE_MISMATCH', message=str(exc),
            scope={'timetable_mode': 'administrative', 'mode_source': 'school_current_setting'})
    except ValueError as exc:
        return _tool_response(name, ok=False, code='MISSING_SCOPE', message=str(exc),
            scope=q.model_dump(exclude_none=True, exclude={'limit', 'offset'}))
    if name == 'lookup_student_choices':
        data = await _choices(session, tenant_id, e)
    elif name == 'lookup_teaching_assignments':
        data = await _assignments(session, tenant_id, e)
    elif name == 'lookup_timetable':
        data = {**_page([s for s in e.lessons if e.matches(s)], e.query), 'missing_data': e.missing,
                'saved_only': True}
    else:
        data = _conflicts(e)
    return _tool_response(name, scope=e.scope, code='OK' if data['total'] else 'EMPTY_RESULT',
        message='已查询保存数据；分页总数与汇总基于完整查询范围，不含未保存预览。缺少名单不能据此判定排课失败；无碰撞不等于全部规则通过。',
        data=data)
