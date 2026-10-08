"""Pure joint timetable preview and independent audit. No database writes."""
from collections import Counter, defaultdict
from ortools.sat.python import cp_model


def check_hour_bounds(total, work, weekend, slots, required):
    """Necessary bounds only; a passing count is not a feasible timetable proof."""
    if total < len(required):
        return f'实际每周{total}节，最低需要{len(required)}节，少{len(required) - total}节；请增加课时或缩小最低排满范围'
    if total > len(slots):
        return f'实际每周{total}节，当前开放课位上限{len(slots)}节，多{total - len(slots)}节；请减少课时或开放更多课位'
    for label, hours, predicate in (
        ('工作日', work, lambda day: day <= 5),
        ('周末', weekend, lambda day: day >= 6),
    ):
        if hours is None:
            continue  # Legacy unsplit walk hours remain a solver decision.
        minimum = sum(predicate(day) for day, _ in required)
        maximum = sum(predicate(day) for day, _ in slots)
        if hours < minimum:
            return f'{label}实际{hours}节，最低需要{minimum}节，少{minimum - hours}节；请调整工作日与周末课时分配'
        if hours > maximum:
            return f'{label}实际{hours}节，当前开放课位上限{maximum}节，多{hours - maximum}节；请调整课时或课位'
    return None


def trial_calendar(draft, assignments, admins, ag, bg, teachers, room_count, external,
                   *, slots=None, phase_hours=4, saturday_hours=None, subject_allowed=None,
                   blocked_rooms=None, required_slots=None, fixed_teachers=None):
    model = cp_model.CpModel()
    slots = slots if slots is not None else [(d, p) for d in range(1, 7) for p in range(1, 8)]
    required = set(slots) if required_slots is None else set(required_slots)
    if not required.issubset(slots):
        return {'status': 'INFEASIBLE', 'seconds': 0}
    saturday_hours = saturday_hours if saturday_hours is not None else {'A': 1, 'B': 2}
    subject_allowed = subject_allowed or {}
    blocked_rooms = blocked_rooms or {}
    fixed_teachers = fixed_teachers or {}
    weekdays = sorted({d for d, _ in slots if d < 6})
    by_phase = defaultdict(list)
    for c in draft['classes']:
        by_phase[c['phase']].append(c)
    z = {(ph, slot): model.NewBoolVar(f'phase_{ph}_{slot}')
         for ph in by_phase for slot in slots}
    for ph in by_phase:
        model.Add(sum(z[ph, s] for s in slots) == phase_hours)
        configured = [c for c in by_phase[ph] if c.get('weekday_periods') is not None or c.get('weekend_periods') is not None]
        if configured:
            for c in configured:
                work, weekend = c.get('weekday_periods'), c.get('weekend_periods')
                if work is None or weekend is None or min(work, weekend) < 0 or work + weekend != phase_hours:
                    return {'status': 'INFEASIBLE', 'seconds': 0}
                model.Add(sum(z[ph, s] for s in slots if 1 <= s[0] <= 5) == work)
                model.Add(sum(z[ph, s] for s in slots if s[0] in (6, 7)) == weekend)
        else:
            model.Add(sum(z[ph, s] for s in slots if s[0] in (6, 7)) == saturday_hours[ph[0]])
    public, teacher_slots = {}, defaultdict(list)
    for i, a in enumerate(assignments):
        for slot in slots:
            v = model.NewBoolVar(f'public_{i}_{slot}')
            public[i, slot] = v
            teacher_slots[a['teacher_id'], slot].append(v)
        model.Add(sum(public[i, s] for s in slots if s[0] < 6) == int(a['weekday_periods']))
        model.Add(sum(public[i, s] for s in slots if s[0] == 6) == int(a['saturday_periods']))
        for slot in slots:
            if slot[0] == 7:
                model.Add(public[i, slot] == 0)  # Administrative weekend hours currently mean Saturday.
        if a['subject_id'] in subject_allowed:
            for slot in slots:
                if slot not in subject_allowed[a['subject_id']]:
                    model.Add(public[i, slot] == 0)
        # Same weekday spread as production's subject_daily_spread option.
        hours = int(a['weekday_periods'])
        if a['counts_toward_teacher_load']:
            for day in weekdays:
                daily = sum(public[i, s] for s in slots if s[0] == day)
                model.Add(daily >= hours // len(weekdays))
                model.Add(daily <= (hours + len(weekdays) - 1) // len(weekdays))
    for admin in admins:
        indices = [i for i, a in enumerate(assignments) if a['class_id'] == admin]
        for slot in slots:
            occupied = sum(public[i, slot] for i in indices) + z[('A', ag[admin]), slot] + z[('B', bg[admin]), slot]
            model.Add(occupied == 1) if slot in required else model.Add(occupied <= 1)
    selections = {}
    for c in draft['classes']:
        # A configured teacher-to-walk-class relationship is an assignment, not
        # a preference for the solver to override. Joint regrouping can change
        # rosters, but it must keep the teacher mapped to each class sequence.
        pool = [fixed_teachers[c['id']]] if c['id'] in fixed_teachers else teachers[c['subject_id']]
        for teacher in pool:
            sel = model.NewBoolVar(f'teacher_{c["id"]}_{teacher}')
            selections[c['id'], teacher] = sel
            for slot in slots:
                v = model.NewBoolVar(f'walk_{c["id"]}_{teacher}_{slot}')
                phase = z[c['phase'], slot]
                model.Add(v <= sel); model.Add(v <= phase)
                model.Add(v >= sel + phase - 1)
                teacher_slots[teacher, slot].append(v)
        model.Add(sum(selections[c['id'], t] for t in pool) == 1)
    for terms in teacher_slots.values():
        model.Add(sum(terms) <= 1)
    for key in external:
        if key in teacher_slots:
            model.Add(sum(teacher_slots[key]) == 0)
    for slot in slots:
        model.Add(sum(len(cs) * z[ph, slot] for ph, cs in by_phase.items()) <=
                  room_count - len(blocked_rooms.get(slot, set())))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 25
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    result = {'status': solver.StatusName(status), 'seconds': solver.WallTime()}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        result['phase_slots'] = {str(ph): [s for s in slots if solver.Value(z[ph, s])]
                                 for ph in by_phase}
        result['teachers'] = {c['id']: next(t for t in (
            [fixed_teachers[c['id']]] if c['id'] in fixed_teachers else teachers[c['subject_id']])
            if solver.Value(selections[c['id'], t])) for c in draft['classes']}
        result['public'] = [dict(a, weekday=s[0], period=s[1])
            for i, a in enumerate(assignments) for s in slots if solver.Value(public[i, s])]
    return result


def audit_draft(draft, calendar, choices, admin_by_student, assignments, rooms, external,
                *, slots=None, phase_hours=4, blocked_rooms=None, required_slots=None):
    """Independent counting audit: a solver success is not sufficient."""
    classes = {c['id']: c for c in draft['classes']}
    actual_choices, student_slots = defaultdict(list), Counter()
    teacher_slots, room_slots = Counter(), Counter()
    public_hours, walk_hours = Counter(), Counter()
    admin_roster = defaultdict(list)
    for sid, admin in admin_by_student.items():
        admin_roster[admin].append(sid)
    for row in calendar['public']:
        slot = row['weekday'], row['period']
        public_hours[row['id']] += 1
        teacher_slots[row['teacher_id'], slot] += 1
        room_slots[row['room'], slot] += 1
        for sid in admin_roster[row['class_id']]:
            student_slots[sid, slot] += 1
    placements = []
    blocked_rooms = blocked_rooms or {}
    slots = slots if slots is not None else [(d, p) for d in range(1, 7) for p in range(1, 8)]
    required = set(slots) if required_slots is None else set(required_slots)
    for day in sorted({d for d, _ in slots}):
        for period in sorted(p for d, p in slots if d == day):
            slot = (day, period)
            active = [c for c in classes.values() if slot in
                      map(tuple, calendar['phase_slots'][str(c['phase'])])]
            available = sorted((r for r in rooms if r['id'] not in blocked_rooms.get(slot, set())),
                               key=lambda r: r['capacity'])
            for c in sorted(active, key=lambda c: c['size'], reverse=True):
                eligible = next((r for r in available if r['capacity'] >= c['size']), None)
                assert eligible is not None, 'No capacity-compatible room'
                available.remove(eligible)
                teacher = calendar['teachers'][c['id']]
                assert (teacher, slot) not in external, 'Other grade teacher conflict'
                teacher_slots[teacher, slot] += 1
                room_slots[f'shared:{eligible["id"]}', slot] += 1
                walk_hours[c['id']] += 1
                placements.append({'teaching_class_id': c['id'], 'teacher_id': teacher,
                    'subject_id': c['subject_id'], 'room_id': eligible['id'],
                    'weekday': day, 'period': period})
    for cid, sid in draft['members']:
        c = classes[cid]
        actual_choices[sid].append(c['subject_id'])
        for slot in calendar['phase_slots'][str(c['phase'])]:
            student_slots[sid, tuple(slot)] += 1
    assert {sid: sorted(s) for sid, s in actual_choices.items()} == {
        sid: sorted(s) for sid, s in choices.items()}, 'Student choice changed'
    assert all(public_hours[a['id']] == int(a['weekly_periods']) for a in assignments)
    assert all(walk_hours[cid] == phase_hours for cid in classes)
    for cid, c in classes.items():
        if c.get('weekday_periods') is not None or c.get('weekend_periods') is not None:
            placed = [p for p in placements if p['teaching_class_id'] == cid]
            assert sum(1 <= p['weekday'] <= 5 for p in placed) == c.get('weekday_periods'), 'Walk weekday hours mismatch'
            assert sum(p['weekday'] in (6, 7) for p in placed) == c.get('weekend_periods'), 'Walk weekend hours mismatch'
    assert required.issubset(slots), 'Required slot outside grid'
    assert all(student_slots[sid, slot] == 1 for sid in choices
               for slot in required), 'Student gap or collision'
    assert all(count <= 1 for count in student_slots.values()), 'Student collision'
    assert all(slot in slots for _, slot in student_slots), 'Student lesson outside grid'
    assert max(teacher_slots.values()) == max(room_slots.values()) == 1
    assert Counter(cid for cid, _ in draft['members']) == {
        cid: c['size'] for cid, c in classes.items()}
    return {'student_count': len(choices), 'student_subject_changes': 0,
            'student_gaps_1_7': 0, 'student_conflicts': 0, 'teacher_conflicts': 0,
            'room_conflicts': 0, 'public_hours_errors': 0, 'walk_hours_errors': 0}, placements
