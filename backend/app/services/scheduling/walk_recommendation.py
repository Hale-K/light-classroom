"""Read-only feasible walk-slot recommendation with student and room constraints."""
from collections import defaultdict
from math import ceil
from ortools.sat.python import cp_model


def recommend_walk_slots(classes, members, rooms, slots, *, blocked_students=None,
                         blocked_teachers=None, blocked_rooms=None, blocked_subjects=None,
                         blocked_slots=None, time_limit=12):
    blocked_students = blocked_students or {}
    blocked_teachers = blocked_teachers or {}
    blocked_rooms = blocked_rooms or {}
    blocked_subjects = blocked_subjects or {}
    blocked_slots = blocked_slots or set()
    by_student = defaultdict(set)
    by_teacher = defaultdict(set)
    roster = defaultdict(set)
    for class_id, student_id in members:
        roster[class_id].add(student_id)
        by_student[student_id].add(class_id)
    by_id = {c['id']: c for c in classes}
    for c in classes:
        if not isinstance(c['weekly_periods'], int) or c['weekly_periods'] <= 0:
            return {'status': 'blocked', 'message': '请先设置全部教学班的有效周课时'}
        if c['teacher_id'] is None:
            return {'status': 'blocked', 'message': '请先为全部教学班安排教师'}
        by_teacher[c['teacher_id']].add(c['id'])
        if not roster[c['id']]:
            return {'status': 'blocked', 'message': '存在没有学生名单的教学班，请先检查分班结果'}
    if not classes or not rooms or not slots:
        return {'status': 'blocked', 'message': '请先完成教学班、可用教室和基础课位配置'}
    student_hours = {sid: sum(by_id[cid]['weekly_periods'] for cid in cids) for sid, cids in by_student.items()}
    teacher_hours = [sum(by_id[cid]['weekly_periods'] for cid in cids) for cids in by_teacher.values()]
    total = sum(c['weekly_periods'] for c in classes)
    bounds = {'rooms': ceil(total / len(rooms)), 'students': max(student_hours.values(), default=0),
              'teachers': max(teacher_hours, default=0)}
    lower_bound = max(bounds.values())
    model = cp_model.CpModel()
    active = {slot: model.NewBoolVar(f'active_{slot}') for slot in slots}
    x = {}
    available_rooms = {slot: [r for r in rooms if slot not in blocked_rooms.get(r['id'], set())] for slot in slots}
    for c in classes:
        for slot in slots:
            if slot in blocked_slots or slot in blocked_subjects.get(c.get('subject_id'), set()): continue
            if slot in blocked_teachers.get(c['teacher_id'], set()): continue
            if any(slot in blocked_students.get(sid, set()) for sid in roster[c['id']]): continue
            if not any(r['capacity'] >= len(roster[c['id']]) for r in available_rooms[slot]): continue
            x[c['id'], slot] = model.NewBoolVar(f"class_{c['id']}_{slot}")
            model.Add(x[c['id'], slot] <= active[slot])
        variables = [v for (cid, _), v in x.items() if cid == c['id']]
        model.Add(sum(variables) == c['weekly_periods'])
        for day in range(1, 8):
            model.Add(sum(v for (cid, (d, p)), v in x.items() if cid == c['id'] and d == day) <= 2)
    conflict_groups = {tuple(sorted(ids)) for ids in [*by_student.values(), *by_teacher.values()] if len(ids) > 1}
    for slot in slots:
        for ids in conflict_groups:
            model.Add(sum(x[cid, slot] for cid in ids if (cid, slot) in x) <= 1)
        # Nested capacity thresholds are an exact matching condition for room sizes.
        for size in {len(roster[c['id']]) for c in classes}:
            model.Add(sum(x[c['id'], slot] for c in classes if (c['id'], slot) in x and len(roster[c['id']]) >= size)
                      <= sum(r['capacity'] >= size for r in available_rooms[slot]))
    model.Add(sum(active.values()) >= lower_bound)
    peak = model.NewIntVar(0, 12, 'max_daily_walk_windows')
    for day in range(1, 8):
        model.Add(sum(v for (d, p), v in active.items() if d == day) <= peak)
    peak_concurrency = model.NewIntVar(0, len(classes), 'peak_concurrent_walk_classes')
    for slot in slots:
        model.Add(sum(v for (cid, candidate_slot), v in x.items() if candidate_slot == slot) <= peak_concurrency)
    # First reduce simultaneous teaching groups to ease scarce teacher/room load;
    # then keep the timetable compact and spread its windows across the week.
    model.Minimize(peak_concurrency * 1000000 + sum(active.values()) * 10000 + peak * 100
                   + sum(v * (slot[0] * 10 + slot[1]) for slot, v in active.items()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 42
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'status': 'infeasible' if status == cp_model.INFEASIBLE else 'unknown',
                'message': '当前课位、教师、学生或教室条件无法同时满足' if status == cp_model.INFEASIBLE else '计算尚未找到可行方案，请增加可用教室或课位后重试',
                'lower_bound': lower_bound, 'bounds': bounds, 'total_class_periods': total}
    placements = []
    used_rooms = set()
    for slot in slots:
        placed = sorted([c for c in classes if (c['id'], slot) in x and solver.Value(x[c['id'], slot])],
                        key=lambda c: (-len(roster[c['id']]), c['id']))
        free = sorted(available_rooms[slot], key=lambda r: (r['capacity'], r['id']))
        for c in placed:
            room = next(r for r in free if r['capacity'] >= len(roster[c['id']]))
            free.remove(room); used_rooms.add(room['id'])
            placements.append({'teaching_class_id': c['id'], 'class_name': c['name'], 'teacher_id': c['teacher_id'],
                'weekday': slot[0], 'period': slot[1], 'room_id': room['id'], 'room_name': room['name']})
    chosen = sorted({(p['weekday'], p['period']) for p in placements})
    return {'status': 'feasible', 'message': '已找到满足全部教学班课时的无冲突走班方案',
            'lower_bound': lower_bound, 'bounds': bounds, 'recommended_count': len(chosen),
            'slots': [list(slot) for slot in chosen], 'room_ids': sorted(used_rooms), 'placements': placements,
            'student_count': len(student_hours), 'student_hours_min': min(student_hours.values(), default=0),
            'student_hours_max': max(student_hours.values(), default=0), 'total_class_periods': total,
            'room_count': len(rooms), 'peak_concurrent_classes': solver.Value(peak_concurrency),
            'minimal_proven': status == cp_model.OPTIMAL,
            'daily_slot_counts': [sum(day == d for day, period in chosen) for d in range(1, 8)]}
