"""走班协调独立校验：用生产求解器验证「行政课+走班课」联合方案的可行性。

从一次性实验脚本沉淀而来，供 test_walk_coordination_check 等验证使用。
"""
from collections import defaultdict

from ortools.sat.python import cp_model

from app.services.scheduling.core import _assignment_placement_groups
from app.services.scheduling.rules import evaluate_rule_group, rules_for_schedule
from app.services.scheduling import ScheduleItem


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


