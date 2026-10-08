"""Pure, opt-in regrouping draft. Never changes students or saved schedules."""
from collections import Counter, defaultdict

from ortools.sat.python import cp_model


def regroup_walk_students(choices, admin_by_student, a_group_by_admin,
                          b_group_by_admin, b_excluded_subject, *, capacity, class_counts=None,
                          configured_classes=None):
    if capacity < 1 or any(len(subjects) != 2 for subjects in choices.values()):
        raise ValueError('Positive capacity and exactly two walk subjects required')
    model = cp_model.CpModel()
    variables, loads = {}, defaultdict(list)
    for sid, subjects in sorted(choices.items()):
        admin = admin_by_student[sid]
        a, b = a_group_by_admin[admin], b_group_by_admin[admin]
        for subject in sorted(subjects):
            v = model.NewBoolVar(f'a_{sid}_{subject}')
            variables[sid, subject] = v
            loads['A', a, subject].append(v)
            loads['B', b, subject].append(1 - v)
            if subject == b_excluded_subject[b]:
                model.Add(v == 1)
        model.Add(sum(variables[sid, subject] for subject in subjects) == 1)
    peak = model.NewIntVar(0, capacity, 'peak')
    active_by_subject = defaultdict(list)
    active_by_bin, size_by_bin = {}, {}
    for (phase, group, subject), terms in loads.items():
        model.Add(sum(terms) <= peak)
        size = model.NewIntVar(0, capacity, f'size_{phase}_{group}_{subject}')
        model.Add(size == sum(terms))
        size_by_bin[phase, group, subject] = size
        if class_counts is not None:
            active = model.NewBoolVar(f'class_{phase}_{group}_{subject}')
            model.Add(sum(terms) <= capacity * active)
            model.Add(sum(terms) >= active)
            active_by_subject[subject].append(active)
            active_by_bin[phase, group, subject] = active
    if class_counts is not None:
        if set(class_counts) != set().union(*choices.values()) or any(count < 1 for count in class_counts.values()):
            return {'status': 'infeasible'}
        for subject, count in class_counts.items():
            model.Add(sum(active_by_subject[subject]) == count)
    teacher_bin = {}
    shells = defaultdict(list)
    teacher_spreads, class_spreads = [], []
    if configured_classes is not None:
        if class_counts is None or Counter(c['subject_id'] for c in configured_classes) != Counter(class_counts):
            raise ValueError('Configured classes must match the fixed subject class counts')
        for c in configured_classes:
            if c['teacher_id'] is None:
                raise ValueError('Configured classes must have assigned teachers')
            shells[c['subject_id'], c['teacher_id']].append(c['id'])
        for subject in sorted(class_counts):
            bins = [key for key in loads if key[2] == subject]
            teachers = sorted(t for sub, t in shells if sub == subject)
            allocated = defaultdict(list)
            for key in bins:
                choices_for_bin = []
                for teacher in teachers:
                    chosen = model.NewBoolVar(f'teacher_{key}_{teacher}')
                    teacher_bin[key, teacher] = chosen
                    choices_for_bin.append(chosen)
                    load = model.NewIntVar(0, capacity, f'teacher_load_{key}_{teacher}')
                    model.AddMultiplicationEquality(load, [size_by_bin[key], chosen])
                    allocated[teacher].append(load)
                model.Add(sum(choices_for_bin) == active_by_bin[key])
            totals = []
            for teacher in teachers:
                model.Add(sum(teacher_bin[key, teacher] for key in bins) == len(shells[subject, teacher]))
                total = model.NewIntVar(0, len(choices), f'total_{subject}_{teacher}')
                model.Add(total == sum(allocated[teacher]))
                totals.append(total)
            high = model.NewIntVar(0, len(choices), f'teacher_high_{subject}')
            low = model.NewIntVar(0, len(choices), f'teacher_low_{subject}')
            model.AddMaxEquality(high, totals)
            model.AddMinEquality(low, totals)
            teacher_spreads.append(high - low)
            minimum = model.NewIntVar(0, capacity, f'class_low_{subject}')
            maximum = model.NewIntVar(0, capacity, f'class_high_{subject}')
            model.AddMinEquality(minimum, [size_by_bin[key] + capacity * (1 - active_by_bin[key]) for key in bins])
            model.AddMaxEquality(maximum, [size_by_bin[key] for key in bins])
            class_spreads.append(maximum - minimum)
        # Same-subject teacher workload first, then class-size spread, then peak.
        model.Minimize(sum(teacher_spreads) * (capacity * len(class_counts) + 1) * (capacity + 1)
                       + sum(class_spreads) * (capacity + 1) + peak)
    else:
        model.Minimize(peak)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'status': 'infeasible' if status == cp_model.INFEASIBLE else 'unknown'}
    rosters = defaultdict(list)
    for sid, subjects in sorted(choices.items()):
        admin = admin_by_student[sid]
        for subject in sorted(subjects):
            phase = ('A', a_group_by_admin[admin]) if solver.Value(variables[sid, subject]) else (
                'B', b_group_by_admin[admin])
            rosters[*phase, subject].append(sid)
    classes, members = [], []
    remaining_shells = {key: iter(sorted(ids)) for key, ids in shells.items()}
    for cid, (key, students) in enumerate(sorted(rosters.items()), 1):
        classes.append({'id': cid, 'subject_id': key[2], 'phase': key[:2],
                        'size': len(students), 'capacity': capacity})
        if configured_classes is not None:
            teacher = next(t for sub, t in shells if sub == key[2] and solver.Value(teacher_bin[key, t]))
            classes[-1]['configured_class_id'] = next(remaining_shells[key[2], teacher])
        members.extend((cid, sid) for sid in students)
    return {'status': 'feasible', 'classes': classes, 'members': members}
