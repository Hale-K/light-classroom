"""Joint scheduling reads user rules; only groups and timetables are replaced.

No old-data snapshots are created. Student records and choices are never updated.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
import random
import re
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select, or_


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def partition_candidates(counts, subjects, capacity, attempts=12):
    """Bounded candidate search; group counts derive from roster size, not class IDs."""
    if len(subjects) < 2 or not counts:
        raise ValueError('至少需要两个走班学科和一个行政班')
    limit = (len(subjects) - 1) * capacity
    if max(counts.values()) > limit:
        raise ValueError('单个行政班人数超过分组容量，请提高班额或拆分行政班')
    rng = random.Random(42)
    group_count = max(math.ceil(len(counts) / 3), math.ceil(sum(counts.values()) / limit))
    for attempt in range(attempts):
        partitions = []
        for _ in range(2):
            for _retry in range(500):
                ordered = list(sorted(counts)); rng.shuffle(ordered)
                # Balanced sizes: e.g. ten classes become 3,3,2,2 (not fixed IDs).
                sizes = [len(ordered) // group_count + (i < len(ordered) % group_count)
                         for i in range(group_count)]
                groups, start = [], 0
                for size in sizes:
                    groups.append(ordered[start:start + size]); start += size
                if all(sum(counts[c] for c in g) <= limit for g in groups):
                    partitions.append({c: i for i, g in enumerate(groups) for c in g})
                    break
            else:
                raise ValueError('无法按当前班额划分走班组，请调整班额')
        yield (*partitions, {i: subjects[(i + attempt) % len(subjects)] for i in range(group_count)})


def fixed_walk_teacher_mapping(existing_classes, generated_classes):
    """Keep each configured subject/sequence teacher on its regenerated class."""
    teacher_mapping, _ = fixed_walk_class_mapping(existing_classes, generated_classes)
    return teacher_mapping


def fixed_walk_class_mapping(existing_classes, generated_classes):
    """Map a regroup draft onto the existing class shells without changing their IDs."""
    existing_by_subject = defaultdict(list)
    generated_by_subject = defaultdict(list)
    for row in existing_classes:
        existing_by_subject[row.subject_id].append(row)
    for row in generated_classes:
        generated_by_subject[row['subject_id']].append(row)

    teacher_mapping, class_mapping = {}, {}
    for subject_id, generated in generated_by_subject.items():
        current = sorted(existing_by_subject.get(subject_id, []), key=lambda row: row.sequence)
        generated = sorted(generated, key=lambda row: row['id'])
        if not current:
            raise ValueError(f'走班学科 {subject_id} 尚未配置任课关系，请先指定任课教师')
        unassigned = [row.name for row in current if row.teacher_id is None]
        if unassigned:
            raise ValueError(f'走班学科 {subject_id} 的任课关系未指定教师：{"、".join(unassigned)}')
        if len(current) != len(generated):
            raise ValueError(
                f'走班学科 {subject_id} 已配置 {len(current)} 个教学班任课关系，'
                f'本次分班将生成 {len(generated)} 个；为避免擅自调整老师，请先核对教学班和任课关系'
            )
        if any('configured_class_id' in row for row in generated):
            by_id = {row.id: row for row in current}
            mapped_ids = [row.get('configured_class_id') for row in generated]
            if len(set(mapped_ids)) != len(current) or set(mapped_ids) != set(by_id):
                raise ValueError('教学班均衡分配对应关系不完整')
            current = [by_id[row['configured_class_id']] for row in generated]
        for old, new in zip(current, generated):
            teacher_mapping[new['id']] = old.teacher_id
            class_mapping[new['id']] = old.id
    return teacher_mapping, class_mapping


def is_generated_coordination_rule(rule_id):
    """Recognize only IDs emitted by the retired joint-rule writer."""
    return rule_id in {'regroup-daytime-range', 'regroup-student-contiguous'} or bool(
        re.fullmatch(r'regroup-reserve-[1-9]\d*-[1-7]', rule_id))


def user_rule_group(group):
    if group is None:
        return None
    return group.model_copy(deep=True, update={'rules': [r.model_copy(deep=True)
        for r in group.rules if not is_generated_coordination_rule(r.id)]})


def clean_generated_rule_catalog(value, academic_year, term, grade_id):
    """Explicit one-time cleanup; never called by preview or save."""
    cleaned, count = deepcopy(value), 0
    entry = cleaned.get(f'{academic_year}:{term}', {})
    groups = entry.get('groups', [entry])
    for group in groups:
        if group.get('grade_id') != grade_id:
            continue
        rules = group.get('rules', [])
        kept = [r for r in rules if not is_generated_coordination_rule(r.get('id', ''))]
        count += len(rules) - len(kept)
        group['rules'] = kept
        # Multi-group catalogs also carry a flattened copy of the active group.
        if entry is not group and entry.get('id') == group.get('id'):
            entry['rules'] = deepcopy(kept)
    return cleaned, count


def check_supported_user_rules(group):
    unknown = [r.id for r in group.rules if r.enabled and r.code != 'subject_allowed_slots'] if group else []
    if unknown:
        raise ValueError('联合排课暂不支持这些规则，请先检查：' + '、'.join(unknown))


def validate_preview(cached, token, scope, current_fingerprint, now):
    if (not cached or cached.get('token') != token or cached.get('scope') != scope
            or cached.get('expires_at', 0) < now or cached.get('fingerprint') != current_fingerprint):
        raise HTTPException(status_code=409, detail='预览已过期或数据已变化，请重新预览')


def cache_key(body):
    return f'walk_regroup_{body.grade_id}_{body.academic_year}_{body.term}'


async def source_fingerprint(session, tenant_id, lock=False):
    # Hash inputs only; no old-data copy is persisted or returned to the client.
    from app.models.org import (Class, Grade, Student, StudentGradeMembership, StudentClassMembership, TeachingAssignment,
                                CourseHourPlan, Schedule, TenantConfig, User, StaffAppointment, OrganizationUnit, Subject)
    from app.models.gaokao import (StudentSubjectChoice, TeachingClass, TeachingClassStudent,
        TeachingClassSchedule, TeachingSubjectHourPlan, WalkSchedulingPlan, GaokaoScheme)
    from app.models.facility import Room, Building, ResourceAllocationRule, RoomCohortAllocation
    state = {'roster_version': 'semester-membership-v1', 'joint_workflow_version': 'teacher-student-balance-v4'}
    for model in (Grade, Class, Student, StudentGradeMembership, StudentClassMembership, StudentSubjectChoice,
                  TeachingAssignment, CourseHourPlan, Schedule, TeachingClass, TeachingClassStudent,
                  TeachingClassSchedule, TeachingSubjectHourPlan, WalkSchedulingPlan, GaokaoScheme,
                  Room, Building, ResourceAllocationRule, RoomCohortAllocation, StaffAppointment,
                  OrganizationUnit, User, Subject, TenantConfig):
        ownership = or_(model.tenant_id == tenant_id, model.tenant_id.is_(None)) if model == Subject else model.tenant_id == tenant_id
        query = select(model).where(ownership).order_by(model.id)
        if model == TenantConfig:
            query = query.where(~model.config_key.startswith('walk_regroup_'))
        if lock:
            query = query.with_for_update()
        rows = (await session.execute(query)).scalars().all()
        state[model.__tablename__] = [r.model_dump(mode='json') for r in rows]
    return fingerprint(state)


def validate_candidate_rules(group, candidate, admins):
    if group is None:
        return
    from app.services.scheduling.core import ScheduleItem
    from app.services.scheduling.rules import evaluate_rule_group
    public = [ScheduleItem(assignment_id=r['id'], class_id=r['class_id'],
        subject_id=r['subject_id'], teacher_id=r['teacher_id'], weekday=r['weekday'],
        period=r['period'], room=r['room']) for r in candidate['calendar']['public']]
    walk = [ScheduleItem(assignment_id=r['teaching_class_id'], class_id=r['teaching_class_id'],
        subject_id=r['subject_id'], teacher_id=r['teacher_id'], weekday=r['weekday'],
        period=r['period']) for r in candidate['placements']]
    occupied = defaultdict(set)
    for sid, cid in admins.items():
        for r in candidate['calendar']['public']:
            if r['class_id'] == cid:
                occupied[sid].add((r['weekday'], r['period']))
    by_class = defaultdict(list)
    for cid, sid in candidate['members']:
        by_class[cid].append(sid)
    for r in candidate['placements']:
        for sid in by_class[r['teaching_class_id']]:
            occupied[sid].add((r['weekday'], r['period']))
    # Exact occupancy/hours/collisions were independently audited before this rule audit.
    reports = [evaluate_rule_group(group, public, schedule_mode='admin'),
               evaluate_rule_group(group, walk, schedule_mode='walk', shared_items=public,
                   student_occupied_by_parity={'odd': occupied, 'even': occupied})]
    failures = [r for report in reports for r in report.results
                if r.status == 'unresolved' or (r.priority == 'hard' and r.status != 'pass')]
    if failures:
        raise HTTPException(status_code=422, detail='规则校验未通过：' + '；'.join(r.message for r in failures))


def candidate_display(candidate, grade_name, subjects, admins, students, teachers, rooms, slots, choice_profiles=None,
                      configured_names=None):
    """Read-only display of the exact candidate bound to the preview token."""
    sequence, names = Counter(), {}
    for c in candidate['classes']:
        sid = c['subject_id']; sequence[sid] += 1
        names[c['id']] = f'{grade_name}{subjects[sid]}走班{sequence[sid]:02d}'
        if configured_names is not None:
            names[c['id']] = configured_names[candidate['class_id_map'][c['id']]]
    lessons = []
    for kind, rows in [('admin', candidate['calendar']['public']), ('walk', candidate['placements'])]:
        for r in rows:
            cid = r['class_id'] if kind == 'admin' else r['teaching_class_id']
            lessons.append({'kind': kind, 'class_id': cid,
                'class_name': admins[cid] if kind == 'admin' else names[cid],
                'subject_name': subjects[r['subject_id']], 'teacher_id': r['teacher_id'],
                'teacher_name': teachers.get(r['teacher_id'], '未安排'),
                'room': r['room'] if kind == 'admin' else rooms[r['room_id']],
                'weekday': r['weekday'], 'period': r['period']})
    memberships = defaultdict(list)
    for cid, sid in candidate['members']:
        memberships[sid].append(cid)
    return {'lessons': lessons,
        'classes': [{'id': c['id'], 'name': names[c['id']], 'subject_name': subjects[c['subject_id']],
            'student_count': c['size'], 'capacity': c['capacity']} for c in candidate['classes']],
        'admin_classes': [{'id': cid, 'name': name} for cid, name in sorted(admins.items())],
        'students': [{'id': int(sid), 'name': students[int(sid)], 'class_id': cid,
            'class_name': admins[cid], 'teaching_class_ids': memberships[int(sid)],
            **(choice_profiles or {}).get(int(sid), {'primary_subject_name': '', 'secondary_subject_names': []})}
            for sid, cid in candidate['admin_by_student'].items()],
        'slots': [{'weekday': d, 'period': p} for d, p in sorted(slots)]}


async def preview_plan(body, session, tenant_id):
    import asyncio
    from app.api.v1.gaokao import (_regroup_roster, WalkRegroupPreviewIn, _preview_regroup_calendar)
    from app.api.v1.scheduling import _load_rule_group, _load_grid_config
    from app.models.org import Subject, User, TenantConfig, Class, Student
    from app.models.facility import Room
    from app.models.gaokao import StudentSubjectChoice, TeachingClass
    from app.models.enums import BaseUserRole, UserStatus
    from app.services.scheduling.grid_slots import allowed_slots
    from app.services.scheduling.walk_regroup import regroup_walk_students
    before = await source_fingerprint(session, tenant_id)
    grade, selected, admins = await _regroup_roster(body, session, tenant_id)
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term, body.grade_id)
    daytime = allowed_slots(grid, 'daytime')
    if not grid['configured'] or not {(d, p) for d in body.weekdays for p in body.periods}.issubset(
            daytime['odd'] & daytime['even']):
        raise HTTPException(status_code=422, detail='所选节次不在已保存的基础课位中')
    group = user_rule_group(await _load_rule_group(
        session, tenant_id, body.academic_year, body.term, grade_id=body.grade_id))
    # Refuse unreviewed rules before spending time solving.
    try:
        check_supported_user_rules(group)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    existing_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term,
    ).order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars())
    if not existing_classes:
        raise HTTPException(status_code=422, detail='请先生成教学班并安排任课教师，再进行联合排课')
    expected_counts = Counter(c.subject_id for c in existing_classes
                              if c.subject_id in set().union(*selected.values()))
    effective_capacity = body.capacity + body.capacity_overflow
    if any(c.teacher_id is None for c in existing_classes if c.subject_id in expected_counts):
        raise HTTPException(status_code=422, detail='请先为所有教学班指定任课教师')
    candidate = None
    count_matched = False
    for ag, bg, excluded in partition_candidates(Counter(admins.values()),
            sorted(set().union(*selected.values())), effective_capacity, attempts=12):
        config = WalkRegroupPreviewIn(**body.model_dump(), a_groups=ag, b_groups=bg,
                                     b_excluded_subject=excluded)
        draft = await asyncio.to_thread(regroup_walk_students, selected, admins, ag, bg, excluded,
            capacity=effective_capacity, class_counts=dict(expected_counts),
            configured_classes=[{'id': c.id, 'subject_id': c.subject_id, 'teacher_id': c.teacher_id}
                                for c in existing_classes if c.subject_id in expected_counts])
        if draft['status'] != 'feasible':
            continue
        if Counter(c['subject_id'] for c in draft['classes']) != expected_counts:
            continue
        count_matched = True
        calendar = await _preview_regroup_calendar(config, session, tenant_id, grade, selected, admins, draft)
        if not calendar.get('schedule_validated'):
            continue
        candidate = {**draft, **calendar, **config.model_dump(), 'admin_by_student': admins}
        validate_candidate_rules(group, candidate, admins)
        break
    if candidate is None:
        if not count_matched:
            raise HTTPException(status_code=422, detail=(
                '当前分组结果与已生成的各科教学班数量不一致，未改动班级或任课关系。'
                '请调整班额或重新核对教学班数量后再预览'
            ))
        raise HTTPException(status_code=422, detail='当前班额、课时和资源下未找到联合方案，原数据未修改')
    teacher_ids = set(candidate['calendar']['teachers'].values()) | {
        r['teacher_id'] for r in candidate['calendar']['public']}
    active = set((await session.execute(select(User.id).where(User.tenant_id == tenant_id,
        User.id.in_(teacher_ids), User.role == BaseUserRole.teacher, User.status == UserStatus.active))).scalars())
    if active != teacher_ids:
        raise HTTPException(status_code=422, detail='方案中的教师已停用或不属于当前学校')
    if before != await source_fingerprint(session, tenant_id):
        raise HTTPException(status_code=409, detail='计算期间数据已变化，请重新预览')
    subject_names = dict((await session.execute(select(Subject.id, Subject.name).where(
        or_(Subject.tenant_id == tenant_id, Subject.tenant_id.is_(None)),
        ))).all())
    choices = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id, StudentSubjectChoice.student_id.in_(selected),
        StudentSubjectChoice.academic_year == body.academic_year,
        StudentSubjectChoice.effective_term == body.term,
        StudentSubjectChoice.status.in_(['confirmed', 'locked'])))).scalars().all()
    profiles = {c.student_id: {'primary_subject_name': subject_names.get(c.primary_subject_id, ''),
        'secondary_subject_names': sorted(subject_names[sid] for sid in c.secondary_subject_ids)} for c in choices}
    admin_names = dict((await session.execute(select(Class.id, Class.name).where(
        Class.tenant_id == tenant_id, Class.id.in_(set(admins.values()))))).all())
    student_names = dict((await session.execute(select(Student.id, Student.name).where(
        Student.tenant_id == tenant_id, Student.id.in_(selected)))).all())
    teacher_names = dict((await session.execute(select(User.id, User.name).where(
        User.tenant_id == tenant_id, User.id.in_(teacher_ids)))).all())
    room_names = {r.id: f'楼栋{r.building_id} · {r.name}' for r in (await session.execute(
        select(Room).where(Room.tenant_id == tenant_id,
            Room.id.in_({r['room_id'] for r in candidate['placements']})))).scalars()}
    display = candidate_display(candidate, grade.name, subject_names, admin_names,
        student_names, teacher_names, room_names,
        {(d, p) for d, p in daytime['odd'] & daytime['even'] if d in body.weekdays}, profiles,
        configured_names={c.id: c.name for c in existing_classes})
    token = str(uuid4())
    cached = {'token': token, 'scope': [body.grade_id, body.academic_year, body.term],
        'fingerprint': before, 'expires_at': time.time() + 1800,
        'candidate': json.loads(json.dumps(candidate))}
    row = (await session.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == cache_key(body)).with_for_update())).scalar_one_or_none()
    if row:
        row.config_value = cached
    else:
        session.add(TenantConfig(tenant_id=tenant_id, config_key=cache_key(body), config_value=cached))
    await session.commit()
    return {'preview_token': token, 'student_count': len(selected), 'class_count': len(candidate['classes']),
        'audit': candidate['audit'], 'replaced_rule_ids': [],
        **display}


async def persist_candidate(body, candidate, session, tenant_id, user_id):
    """Save the joint timetable and roster into the already-created teaching classes."""
    from app.models.org import Schedule
    from app.models.gaokao import (TeachingClass, TeachingClassStudent, TeachingClassSchedule,
        TeachingSubjectHourPlan, WalkSchedulingPlan, WalkSchedulingRoom, WalkSchedulingSlot)
    from app.models.facility import Room
    scope = (TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
             TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term)
    class_id_map = {int(key): int(value) for key, value in candidate.get('class_id_map', {}).items()}
    expected_generated_ids = {int(row['id']) for row in candidate['classes']}
    if set(class_id_map) != expected_generated_ids:
        raise HTTPException(status_code=409, detail='预览中的教学班对应关系不完整，请重新预览')
    target_class_ids = set(class_id_map.values())
    existing_classes = list((await session.execute(select(TeachingClass).where(
        *scope, TeachingClass.id.in_(target_class_ids)))).scalars()) if target_class_ids else []
    if {row.id for row in existing_classes} != target_class_ids:
        raise HTTPException(status_code=409, detail='已生成的教学班发生变化，请重新预览')
    existing_by_id = {row.id: row for row in existing_classes}
    for generated in candidate['classes']:
        existing = existing_by_id[class_id_map[int(generated['id'])]]
        allowed_capacity = generated.get('capacity', existing.capacity or body.capacity)
        if existing.subject_id != generated['subject_id'] or generated['size'] > allowed_capacity:
            raise HTTPException(status_code=422, detail='学生分班与已生成教学班的科目或班额不匹配，请重新生成教学班')
        existing.capacity = allowed_capacity
    for model in (TeachingClassSchedule, TeachingClassStudent):
        await session.execute(delete(model).where(model.tenant_id == tenant_id,
            model.teaching_class_id.in_(target_class_ids)))
    admins = {int(cid) for cid in candidate['a_groups']}
    await session.execute(delete(Schedule).where(Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year, Schedule.term == body.term,
        Schedule.class_id.in_(admins)))
    ids = class_id_map
    session.add_all([TeachingClassStudent(tenant_id=tenant_id, teaching_class_id=ids[cid], student_id=sid)
                     for cid, sid in candidate['members']])
    rooms = {r.id: r for r in (await session.execute(select(Room).where(Room.tenant_id == tenant_id,
        Room.id.in_({r['room_id'] for r in candidate['placements']})))).scalars()}
    session.add_all([TeachingClassSchedule(tenant_id=tenant_id, teaching_class_id=ids[r['teaching_class_id']],
        subject_id=r['subject_id'], teacher_id=r['teacher_id'], academic_year=body.academic_year,
        term=body.term, weekday=r['weekday'], period=r['period'],
        room=f'楼栋{rooms[r["room_id"]].building_id} · {rooms[r["room_id"]].name}')
        for r in candidate['placements']])
    session.add_all([Schedule(tenant_id=tenant_id, academic_year=body.academic_year, term=body.term,
        class_id=r['class_id'], subject_id=r['subject_id'], teacher_id=r['teacher_id'],
        weekday=r['weekday'], period=r['period'], room=r['room'], week_parity='all')
        for r in candidate['calendar']['public']])
    plan = (await session.execute(select(WalkSchedulingPlan).where(WalkSchedulingPlan.tenant_id == tenant_id,
        WalkSchedulingPlan.grade_id == body.grade_id, WalkSchedulingPlan.academic_year == body.academic_year,
        WalkSchedulingPlan.term == body.term).with_for_update())).scalar_one_or_none()
    if plan:
        for model in (WalkSchedulingSlot, WalkSchedulingRoom):
            await session.execute(delete(model).where(model.plan_id == plan.id))
        plan.revision += 1
    else:
        plan = WalkSchedulingPlan(tenant_id=tenant_id, grade_id=body.grade_id,
                                 academic_year=body.academic_year, term=body.term)
        session.add(plan); await session.flush()
    slots = {(r['weekday'], r['period']) for r in candidate['placements']}
    session.add_all([WalkSchedulingSlot(plan_id=plan.id, weekday=d, period=p) for d, p in sorted(slots)])
    session.add_all([WalkSchedulingRoom(plan_id=plan.id, room_id=rid) for rid in sorted(rooms)])
    await session.flush()
    return {'saved': True, 'class_count': len(ids), 'student_count': candidate['audit']['student_count'],
            'public_lessons': len(candidate['calendar']['public']), 'walk_lessons': len(candidate['placements']),
            'audit': candidate['audit']}


async def save_plan(body, session, tenant_id, user_id):
    from app.models.org import Grade, TenantConfig
    grade = (await session.execute(select(Grade).where(Grade.id == body.grade_id,
        Grade.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail='年级不存在')
    row = (await session.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == cache_key(body)).with_for_update())).scalar_one_or_none()
    cached = row.config_value if row and isinstance(row.config_value, dict) else {}
    scope = [body.grade_id, body.academic_year, body.term]
    if cached.get('token') == body.preview_token and cached.get('scope') == scope and cached.get('saved_result'):
        return cached['saved_result']
    validate_preview(cached, body.preview_token, scope, await source_fingerprint(session, tenant_id, lock=True), time.time())
    candidate = cached['candidate']
    from app.api.v1.scheduling import _load_rule_group
    group = user_rule_group(await _load_rule_group(
        session, tenant_id, body.academic_year, body.term, grade_id=body.grade_id))
    validate_candidate_rules(group, candidate,
                             {int(k): v for k, v in candidate['admin_by_student'].items()})
    try:
        result = await persist_candidate(body, candidate, session, tenant_id, user_id)
        # Keep only the idempotency receipt, not an old-data backup or a roster copy.
        row.config_value = {'token': body.preview_token, 'scope': scope, 'saved_result': result}
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        raise
