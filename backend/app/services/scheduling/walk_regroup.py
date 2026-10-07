"""Pure, opt-in regrouping draft. Never changes students or saved schedules."""
from collections import defaultdict

from ortools.sat.python import cp_model


def regroup_walk_students(choices, admin_by_student, a_group_by_admin,
                          b_group_by_admin, b_excluded_subject, *, capacity):
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
    for terms in loads.values():
        model.Add(sum(terms) <= peak)
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
    for cid, (key, students) in enumerate(sorted(rosters.items()), 1):
        classes.append({'id': cid, 'subject_id': key[2], 'phase': key[:2],
                        'size': len(students), 'capacity': capacity})
        members.extend((cid, sid) for sid in students)
    return {'status': 'feasible', 'classes': classes, 'members': members}
