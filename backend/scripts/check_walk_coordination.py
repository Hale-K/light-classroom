"""Joint coordination check; --apply saves verified rules, never timetables.

The first experiment relaxes administrative teacher/subject constraints. The
full check then verifies the resulting windows with both production solvers.
"""
import asyncio
import json
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models
from ortools.sat.python import cp_model
from sqlalchemy import select, text
from app.api.v1.gaokao import (
    WalkRecommendationIn, recommend_walk_configuration, _map_student_admin_classes_to_term,
)
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User, Student, Class, Schedule
from app.api.v1.scheduling import GenerateIn, _generation_assignment_payloads
from app.services.scheduling.core import _assignment_placement_groups


def check(data, admin_by_student, public_counts, room_multiplier=1, split_teachers=False, tail_reserve=False, full_admin=False):
    model = cp_model.CpModel()
    slots = data['slots']
    classes = data['classes']
    by_student, by_teacher, roster = defaultdict(set), defaultdict(set), defaultdict(set)
    for cid, sid in data['members']:
        by_student[sid].add(cid)
        roster[cid].add(sid)
    for c in classes:
        by_teacher[c['id'] if split_teachers else c['teacher_id']].add(c['id'])
    x = {(c['id'], slot): model.NewBoolVar(f"w_{c['id']}_{slot}") for c in classes for slot in slots}
    for c in classes:
        model.Add(sum(x[c['id'], slot] for slot in slots) == c['weekly_periods'])
    for slot in slots:
        for cids in by_teacher.values():
            model.Add(sum(x[cid, slot] for cid in cids) <= 1)
        for size in {len(s) for s in roster.values()}:
            model.Add(sum(x[c['id'], slot] for c in classes if len(roster[c['id']]) >= size)
                      <= room_multiplier * sum(r['capacity'] >= size for r in data['rooms']))
    public = {(parity, cid, slot): model.NewBoolVar(f'a_{parity}_{cid}_{slot}')
              for parity, counts in public_counts.items() for cid in counts for slot in slots}
    if full_admin:
        lessons = defaultdict(list)
        teacher_slots = defaultdict(list)
        subject_slots = defaultdict(list)
        for index, a in enumerate(data['assignments']):
            for days, required in _assignment_placement_groups(a, days=6):
                if required != int(required) or a.get('week_parity', 'all') != 'all':
                    raise ValueError('This diagnostic supports whole-week integer lessons only')
                candidates = [(day, period) for day, period in slots if day in days
                              and (a['subject_id'] != data['meeting_subject'] or (day, period) == (5, 7))]
                variables = []
                for slot in candidates:
                    v = model.NewBoolVar(f'lesson_{index}_{slot}')
                    variables.append(v)
                    lessons[a['class_id'], slot].append(v)
                    subject_slots[a['class_id'], a['subject_id'], slot[0]].append(v)
                    if a['teacher_id']:
                        teacher_slots[a['teacher_id'], slot].append(v)
                model.Add(sum(variables) == int(required))
            weekday_hours = int(a.get('weekday_periods') or 0)
            base, remainder = divmod(weekday_hours, 5)
            for day in range(1, 7):
                terms = subject_slots[a['class_id'], a['subject_id'], day]
                model.Add(sum(terms) <= (2 if weekday_hours > 5 else 1))
                if day <= 5:
                    model.Add(sum(terms) <= base + bool(remainder))
                    if weekday_hours > 5:
                        model.Add(sum(terms) >= base)
        for parity, cid, slot in public:
            model.Add(public[parity, cid, slot] == sum(lessons[cid, slot]))
        for slot in slots:
            for teacher in set(by_teacher) | {a['teacher_id'] for a in data['assignments'] if a['teacher_id']}:
                model.Add(sum(teacher_slots[teacher, slot]) + sum(x[cid, slot] for cid in by_teacher[teacher]) <= 1)
    for parity, counts in public_counts.items():
        for cid, count in counts.items():
            model.Add(sum(public[parity, cid, slot] for slot in slots) == count)
            if tail_reserve:
                for day, period in slots:
                    if period >= 8 or (day != 5 and period >= 6):
                        model.Add(public[parity, cid, (day, period)] == 0)
            if (5, 7) in slots:
                model.Add(public[parity, cid, (5, 7)] == 1)  # Saved Friday class-meeting rule.
    profiles = {(admin_by_student[sid], tuple(sorted(cids))) for sid, cids in by_student.items()}
    for parity in public_counts:
        for admin_cid, cids in profiles:
            occupied = {}
            for slot in slots:
                occupied[slot] = public[parity, admin_cid, slot] + sum(x[cid, slot] for cid in cids)
                model.Add(occupied[slot] <= 1)
            for day, periods in data['kwargs']['student_contiguous_periods'].items():
                for before, after in zip(sorted(periods), sorted(periods)[1:]):
                    model.Add(occupied.get((day, before), 0) >= occupied.get((day, after), 0))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    result = dict(room_multiplier=room_multiplier, split_teachers=split_teachers, tail_reserve=tail_reserve, full_admin=full_admin,
                  status=solver.StatusName(status), seconds=round(solver.WallTime(), 2))
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result['walk_windows'] = sorted({slot for c in classes for slot in slots if solver.Value(x[c['id'], slot])})
        result['public_windows'] = {cid: sorted(slot for slot in slots if solver.Value(public['odd', cid, slot]))
                                    for cid in public_counts['odd']}
        if full_admin:
            from app.services.scheduling.cpsat import solve_daytime_cpsat
            from app.services.scheduling.walk_recommendation import recommend_walk_slots
            allowed = {cid: {slot: set() for slot in slots if slot not in windows}
                       for cid, windows in result['public_windows'].items()}
            public_result = solve_daytime_cpsat(data['assignments'], days=6, periods_per_day=9,
                class_slot_allowed_subjects=allowed, subject_forbidden_slots={data['meeting_subject']: set(slots) - {(5, 7)}},
                subject_daily_spread=True, max_time_seconds=20, polish_seconds=0, num_search_workers=8)
            result['production_admin_solver'] = public_result.status
            if public_result.status in ('OPTIMAL', 'FEASIBLE'):
                blocked_students, blocked_teachers = defaultdict(set), defaultdict(set)
                for item in public_result.items:
                    slot = item.weekday, item.period
                    if item.teacher_id:
                        blocked_teachers[item.teacher_id].add(slot)
                    for sid, cid in admin_by_student.items():
                        if cid == item.class_id:
                            blocked_students[sid].add(slot)
                preview = recommend_walk_slots(classes, data['members'], data['rooms'], slots,
                    blocked_students=blocked_students, blocked_teachers=blocked_teachers,
                    student_contiguous_periods=data['kwargs']['student_contiguous_periods'])
                result['production_walk_solver'] = {k: preview.get(k) for k in (
                    'status', 'message', 'student_prefix_gap_count', 'recommended_slot_count')}
                result['_public_items'] = public_result.items
                result['_walk_result'] = preview
    return result


async def main():
    captured = {}
    def capture(classes, members, rooms, slots, **kwargs):
        captured.update(classes=classes, members=members, rooms=rooms, slots=slots, kwargs=kwargs)
        return {'status': 'diagnostic_only'}
    async with AsyncSessionLocal() as session:
        apply = '--apply' in sys.argv
        if not apply:
            await session.execute(text('SET TRANSACTION READ ONLY'))
        user = (await session.execute(select(User).where(User.phone == sys.argv[1]))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            with patch('app.services.scheduling.walk_recommendation.recommend_walk_slots', capture):
                await recommend_walk_configuration(WalkRecommendationIn(
                    grade_id=12, academic_year='2026-2027', term='2'), session, user.tenant_id)
            sids = {sid for _, sid in captured['members']}
            students = (await session.execute(select(Student.id, Student.class_id).where(
                Student.tenant_id == user.tenant_id, Student.id.in_(sids)))).all()
            source_ids = {cid for _, cid in students}
            sources = list((await session.execute(select(Class).where(Class.id.in_(source_ids),
                Class.tenant_id == user.tenant_id))).scalars())
            targets = list((await session.execute(select(Class).where(Class.tenant_id == user.tenant_id,
                Class.grade_id == 12, Class.academic_year == '2026-2027', Class.term == '2'))).scalars())
            assignments = await _generation_assignment_payloads(session, GenerateIn(
                academic_year='2026-2027', term='2', class_ids=[c.id for c in targets]), user.tenant_id)
            print(json.dumps([dict(class_id=a['class_id'], subject_id=a['subject_id'],
                teacher=a['teacher_id'], weekday=a.get('weekday_periods'), saturday=a.get('saturday_periods'),
                weekly=a.get('weekly_periods')) for a in assignments if a['class_id'] == targets[0].id]), flush=True)
            captured['assignments'] = assignments
            from app.models.org import Subject
            captured['meeting_subject'] = (await session.execute(select(Subject.id).where(
                Subject.tenant_id == user.tenant_id, Subject.name == '班会'))).scalar_one()
            print(json.dumps(dict(public_room_names=sorted({a.get('room') or '' for a in assignments}))), flush=True)
            mapping = _map_student_admin_classes_to_term(source_ids, sources, targets)
            admin_by_student = {sid: mapping[cid] for sid, cid in students}
            rows = list((await session.execute(select(Schedule).where(Schedule.tenant_id == user.tenant_id,
                Schedule.class_id.in_(set(mapping.values())), Schedule.academic_year == '2026-2027',
                Schedule.term == '2'))).scalars())
            counts = {parity: defaultdict(int) for parity in ('odd', 'even')}
            for row in rows:
                if (row.weekday, row.period) not in captured['slots']:
                    continue
                for parity in counts:
                    if row.week_parity in ('all', parity):
                        counts[parity][row.class_id] += 1
            reached = defaultdict(set)
            for cid, sid in captured['members']:
                reached[cid].add(admin_by_student[sid])
            print(json.dumps(dict(students=len(sids), teaching_classes=len(captured['classes']),
                rooms=len(captured['rooms']), public_counts=counts,
                admin_classes_per_walk_class={cid: len(ids) for cid, ids in reached.items()})), flush=True)
            for multiplier, split, tail in ((1, False, True),):
                result = await asyncio.to_thread(check, captured, admin_by_student, counts, multiplier, split, tail, True)
                print(json.dumps({k: v for k, v in result.items() if not k.startswith('_')}, ensure_ascii=False), flush=True)
                if apply:
                    if result.get('production_walk_solver', {}).get('status') != 'feasible':
                        raise RuntimeError('No verified production-solver pair; configuration unchanged')
                    from app.api.v1.scheduling import _load_rule_catalog, save_rule_group
                    from app.services.scheduling.rules import (
                        RuleDefinition, compile_rule_group, evaluate_rule_group, rules_for_schedule,
                    )
                    from app.services.scheduling.core import ScheduleItem
                    groups, active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
                    group = next(g for g in groups if g.grade_id == 12 and g.id == active)
                    public_windows = {int(cid): set(windows) for cid, windows in result['public_windows'].items()}
                    # Common tails share one rule; retain only genuine class-specific differences.
                    common_days, extras = defaultdict(list), defaultdict(list)
                    for day in sorted({d for d, _ in captured['slots']}):
                        by_class = {cid: {p for d, p in captured['slots']
                                        if d == day and (d, p) not in windows}
                                    for cid, windows in public_windows.items()}
                        common = set.intersection(*by_class.values())
                        if common:
                            common_days[tuple(sorted(common))].append(day)
                        for cid, periods in by_class.items():
                            extra = tuple(sorted(periods - common))
                            if extra:
                                extras[day, extra].append(cid)
                    reservations = []
                    class_names = {c.id: c.name for c in targets}
                    day_name = lambda day: '周' + '一二三四五六日'[day - 1]
                    for index, (periods, days) in enumerate(common_days.items()):
                        reservations.append(RuleDefinition(id=f'walk-coordinated-{index+1}',
                            title=f"走班预留：{'、'.join(map(day_name, days))}第{periods[0]}–{periods[-1]}节",
                            code='slot_forbidden', priority='hard', schedule_scope='admin',
                            target={'type': 'global'}, weekdays=days, periods=list(periods)))
                    for (day, periods), class_ids in extras.items():
                        reservations.append(RuleDefinition(id=f'walk-coordinated-{len(reservations)+1}',
                            title=f"{'、'.join(class_names[cid] for cid in class_ids)}：{day_name(day)}第{periods[0]}节预留",
                            code='slot_forbidden', priority='hard', schedule_scope='admin',
                            target={'type': 'class', 'ids': class_ids}, weekdays=[day], periods=list(periods)))
                    keep = [r.model_copy(update={'periods': list(range(1, 8))})
                            if r.id == 'student-gap-minimize' else r for r in group.rules
                            if r.id not in {'walk-reserve-689', 'walk-reserve-7'} and not r.id.startswith('walk-coordinated-')]
                    proposal = group.model_copy(update={'rules': keep + reservations})
                    assert all(r.status == 'ready' for r in compile_rule_group(proposal))
                    admin_check = evaluate_rule_group(rules_for_schedule(proposal, 'admin'),
                        result['_public_items'], schedule_mode='admin')
                    assert admin_check.valid, admin_check.model_dump()
                    occupied = {parity: defaultdict(set) for parity in ('odd', 'even')}
                    for item in result['_public_items']:
                        for sid, cid in admin_by_student.items():
                            if cid == item.class_id:
                                for parity in occupied:
                                    occupied[parity][sid].add((item.weekday, item.period))
                    walk_items = []
                    teaching_by_id = {c['id']: c for c in captured['classes']}
                    for item in result['_walk_result']['placements']:
                        cid = item['teaching_class_id']
                        walk_items.append(ScheduleItem(assignment_id=-cid, class_id=-cid,
                            subject_id=teaching_by_id[cid]['subject_id'], teacher_id=item['teacher_id'],
                            weekday=item['weekday'], period=item['period'], room=str(item['room_id'])))
                        for tcid, sid in captured['members']:
                            if tcid == cid:
                                for parity in occupied:
                                    occupied[parity][sid].add((item['weekday'], item['period']))
                    walk_check = evaluate_rule_group(rules_for_schedule(proposal, 'walk'), walk_items,
                        schedule_mode='walk', shared_items=result['_public_items'], student_occupied_by_parity=occupied)
                    assert walk_check.valid, walk_check.model_dump()
                    first, first_active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
                    first_dump = [g.model_dump() for g in first]
                    backup = Path(__file__).resolve().parents[2] / '.codex/backups' / (
                        'before-coordinated-reserve-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_text(json.dumps({'active_id': active, 'groups': [g.model_dump(mode='json') for g in groups]},
                        ensure_ascii=False, indent=2), encoding='utf-8')
                    await save_rule_group(proposal, session, user, user.tenant_id)
                    after, after_active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
                    assert active == after_active
                    assert next(g for g in after if g.id == group.id).model_dump() == proposal.model_dump()
                    assert [g.model_dump() for g in after if g.id != group.id] == [g.model_dump() for g in groups if g.id != group.id]
                    first_after, first_active_after = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
                    assert first_dump == [g.model_dump() for g in first_after] and first_active == first_active_after
                    print('Saved verified coordination rules only; all existing timetables and term 1 unchanged.', flush=True)
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
