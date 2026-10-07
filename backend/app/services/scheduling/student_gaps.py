"""Student internal gaps: public + walk courses, odd/even weeks separately."""
from collections import defaultdict


def build_student_self_study(occupied_by_parity, periods_by_day):
    """Derived independent study, never a subject lesson or teacher assignment."""
    selected = {(day, p) for day, periods in periods_by_day.items() for p in periods}
    return {parity: {sid: selected - set(slots) for sid, slots in occupied.items()}
            for parity, occupied in occupied_by_parity.items()}


def complete_student_timetable(entries, periods_by_day, context):
    """Materialize a personal view from saved courses; never hide collisions."""
    occupied = {'odd': {0: set()}, 'even': {0: set()}}
    for entry in entries:
        slot = (entry['weekday'], entry['period'])
        for parity in occupied:
            if entry.get('week_parity', 'all') in ('all', parity):
                if slot in occupied[parity][0]:
                    raise ValueError(f"课表冲突：周{slot[0]}第{slot[1]}节，请重新生成走班课表")
                occupied[parity][0].add(slot)
    studies = build_student_self_study(occupied, periods_by_day)
    result = list(entries)
    for day, periods in periods_by_day.items():
        for period in periods:
            parities = [parity for parity in occupied if (day, period) in studies[parity][0]]
            if parities:
                result.append({**context, 'id': -1000000 - day * 100 - period,
                    'weekday': day, 'period': period, 'subject_id': 0,
                    'subject_name': '自主学习', 'is_self_study': True,
                    'teacher_id': None, 'teacher_name': '',
                    'week_parity': 'all' if len(parities) == 2 else parities[0]})
    return sorted(result, key=lambda entry: (entry['weekday'], entry['period']))


def count_student_prefix_gaps(occupied_by_parity, periods_by_day):
    """Empty selected periods before the last occupied selected period."""
    total = 0
    for occupied in occupied_by_parity.values():
        for slots in occupied.values():
            for day, periods in periods_by_day.items():
                last = max((p for p in periods if (day, p) in slots), default=0)
                total += sum(p < last and (day, p) not in slots for p in periods)
    return total


def add_student_contiguous_constraints(model, x, by_student, fixed_by_parity, periods_by_day):
    profiles = {(tuple(sorted(classes)), tuple(sorted(fixed.get(sid, set()))))
                for fixed in fixed_by_parity.values() for sid, classes in by_student.items()}
    for classes, fixed in profiles:
        fixed = set(fixed)
        for day, periods in periods_by_day.items():
            occupied = [1 if (day, p) in fixed else
                        sum(x[cid, (day, p)] for cid in classes if (cid, (day, p)) in x)
                        for p in sorted(periods)]
            for before, after in zip(occupied, occupied[1:]):
                model.Add(before >= after)


def count_student_gaps(occupied_by_parity, weekdays, preferred_periods=None):
    total = 0
    for occupied in occupied_by_parity.values():
        for slots in occupied.values():
            for day in weekdays:
                periods = {p for d, p in slots if d == day}
                if periods:
                    gaps = set(range(min(periods), max(periods) + 1)) - periods
                    if preferred_periods is not None:
                        gaps.intersection_update(preferred_periods.get(day, []))
                    total += len(gaps)
    return total


def count_student_unfilled(occupied_by_parity, preferred_periods):
    return sum((day, period) not in slots for occupied in occupied_by_parity.values()
               for slots in occupied.values() for day, periods in preferred_periods.items() for period in periods)


def add_student_gap_cost(model, x, by_student, fixed_by_parity, weekdays, preferred_periods=None):
    # Equivalent rosters share Boolean variables, but cost counts every student.
    profiles = defaultdict(int)
    for parity, fixed in fixed_by_parity.items():
        for sid, classes in by_student.items():
            profiles[(tuple(sorted(classes)), tuple(sorted(fixed.get(sid, set()))))] += 1
    costs = []
    missing_costs = []
    for index, ((classes, fixed), weight) in enumerate(profiles.items()):
        fixed = set(fixed)
        for day in weekdays:
            candidates = {p for cid, (d, p) in x if cid in classes and d == day}
            candidates.update(p for d, p in fixed if d == day)
            if preferred_periods is not None:
                candidates.update(preferred_periods.get(day, []))
            if not candidates:
                continue
            occupied = []
            for period in range(1, max(candidates) + 1):
                if (day, period) in fixed:
                    occupied.append(1)
                else:
                    variables = [x[cid, (day, period)] for cid in classes if (cid, (day, period)) in x]
                    present = model.NewBoolVar(f'student_present_{index}_{day}_{period}')
                    model.Add(present == sum(variables))
                    occupied.append(present)
            if preferred_periods is not None:
                missing_costs.extend((1 - occupied[p - 1]) * weight for p in preferred_periods.get(day, []))
            for p in range(1, len(occupied) - 1):
                if preferred_periods is not None and p + 1 not in preferred_periods.get(day, []):
                    continue
                before = model.NewBoolVar(f'before_{index}_{day}_{p}')
                after = model.NewBoolVar(f'after_{index}_{day}_{p}')
                gap = model.NewBoolVar(f'gap_{index}_{day}_{p}')
                model.AddMaxEquality(before, occupied[:p])
                model.AddMaxEquality(after, occupied[p + 1:])
                model.Add(gap <= before)
                model.Add(gap <= after)
                model.Add(gap <= 1 - occupied[p])
                model.Add(gap >= before + after - occupied[p] - 1)
                costs.append(gap * weight)
    # First keep lessons inside preferred periods; then reduce internal holes.
    gap_bound = len(by_student) * len(fixed_by_parity) * len(weekdays) * 12
    return sum(missing_costs) * (gap_bound + 1) + sum(costs)
