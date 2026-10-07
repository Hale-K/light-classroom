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
    state = {'roster_version': 'semester-membership-v1', 'joint_workflow_version': 'minimum-range-v3'}
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


async def preview_plan(body, session, tenant_id):
    import asyncio
    from app.api.v1.gaokao import (_regroup_roster, WalkRegroupPreviewIn, _preview_regroup_calendar)
    from app.api.v1.scheduling import _load_rule_group, _load_grid_config
    from app.models.org import Subject, User, TenantConfig
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
    candidate = None
    for ag, bg, excluded in partition_candidates(Counter(admins.values()),
            sorted(set().union(*selected.values())), body.capacity, attempts=4):
        config = WalkRegroupPreviewIn(**body.model_dump(), a_groups=ag, b_groups=bg,
                                     b_excluded_subject=excluded)
        draft = await asyncio.to_thread(regroup_walk_students, selected, admins, ag, bg, excluded,
                                       capacity=body.capacity)
        if draft['status'] != 'feasible':
            continue
        calendar = await _preview_regroup_calendar(config, session, tenant_id, grade, selected, admins, draft)
        if not calendar.get('schedule_validated'):
            continue
        candidate = {**draft, **calendar, **config.model_dump(), 'admin_by_student': admins}
        validate_candidate_rules(group, candidate, admins)
        break
    if candidate is None:
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
        Subject.id.in_({c['subject_id'] for c in candidate['classes']})))).all())
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
        'classes': [{'id': c['id'], 'subject_name': subject_names[c['subject_id']],
                     'student_count': c['size'], 'capacity': c['capacity']} for c in candidate['classes']]}


async def persist_candidate(body, candidate, session, tenant_id, user_id):
    """Replace the exact scope in the caller's transaction; never creates a backup."""
    from app.models.org import Schedule, Subject, Grade
    from app.models.gaokao import (TeachingClass, TeachingClassStudent, TeachingClassSchedule,
        TeachingSubjectHourPlan, WalkSchedulingPlan, WalkSchedulingRoom, WalkSchedulingSlot)
    from app.models.facility import Room
    scope = (TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
             TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term)
    old_ids = list((await session.execute(select(TeachingClass.id).where(*scope))).scalars())
    if old_ids:
        for model in (TeachingClassSchedule, TeachingClassStudent):
            await session.execute(delete(model).where(model.tenant_id == tenant_id,
                model.teaching_class_id.in_(old_ids)))
        await session.execute(delete(TeachingClass).where(*scope))
    admins = {int(cid) for cid in candidate['a_groups']}
    await session.execute(delete(Schedule).where(Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year, Schedule.term == body.term,
        Schedule.class_id.in_(admins)))
    subjects = dict((await session.execute(select(Subject.id, Subject.name).where(
        or_(Subject.tenant_id == tenant_id, Subject.tenant_id.is_(None))))).all())
    grade = await session.get(Grade, body.grade_id)
    plans = {p.subject_id: p for p in (await session.execute(select(TeachingSubjectHourPlan).where(
        TeachingSubjectHourPlan.tenant_id == tenant_id, TeachingSubjectHourPlan.grade_id == body.grade_id,
        TeachingSubjectHourPlan.academic_year == body.academic_year,
        TeachingSubjectHourPlan.term == body.term))).scalars()}
    sequence, ids = Counter(), {}
    for c in candidate['classes']:
        sid = c['subject_id']; sequence[sid] += 1
        row = TeachingClass(tenant_id=tenant_id, grade_id=body.grade_id, academic_year=body.academic_year,
            term=body.term, subject_id=sid, sequence=sequence[sid], capacity=c['capacity'],
            name=f'{grade.name}{subjects[sid]}走班{sequence[sid]:02d}',
            weekly_periods=plans[sid].weekly_periods, hour_plan_id=plans[sid].id,
            weekday_periods=plans[sid].weekday_periods, weekend_periods=plans[sid].weekend_periods,
            teacher_id=candidate['calendar']['teachers'].get(c['id'],
                candidate['calendar']['teachers'].get(str(c['id']))), source='selection', status='generated')
        session.add(row); await session.flush()
        ids[c['id']] = row.id
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
