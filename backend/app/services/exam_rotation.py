"""Build school elective exams around student combinations, with no idle waves."""
from collections import defaultdict
from dataclasses import replace

from app.services.scheduling import generate_exam_schedule


def build_rotation(courses, rosters, names, *, start_date, sessions, excluded_dates,
                   room, allow_batches=False):
    common = {'语文', '数学', '英语', '外语'}
    primary = {'物理', '历史'}
    secondary = {'化学', '地理', '政治', '思想政治', '生物', '生物学'}
    participants = set().union(*(set(ids) for ids in rosters.values()))
    if not participants:
        raise ValueError('所选范围没有参考学生')
    by_student = defaultdict(list)
    for course in courses:
        for sid in rosters.get(course['id'], []):
            by_student[sid].append(course)
    for sid in sorted(participants):
        selected = by_student[sid]
        if (sum(names.get(c['subject_id']) in common for c in selected) != 3 or
                sum(names.get(c['subject_id']) in primary for c in selected) != 1 or
                sum(names.get(c['subject_id']) in secondary for c in selected) != 2):
            raise ValueError(f'考生 {sid} 的参考科目不满足3+1+2；同步排考需选齐三门共同科目、一门首选和两门再选科目')
    graph = defaultdict(set)
    pairs = {}
    for sid, selected in by_student.items():
        pair = sorted(c['subject_id'] for c in selected if names.get(c['subject_id']) in secondary)
        pairs[sid] = pair
        a, b = pair
        graph[a].add(b)
        graph[b].add(a)
    colors = {}
    needs_batches = False
    for root in sorted(graph):
        if root in colors:
            continue
        colors[root] = 0
        pending = [root]
        while pending:
            a = pending.pop()
            for b in sorted(graph[a]):
                if b not in colors:
                    colors[b] = 1 - colors[a]
                    pending.append(b)
                elif colors[a] == colors[b]:
                    needs_batches = True
    if needs_batches and not allow_batches:
        raise ValueError('当前再选科目组合无法在“同科目只考一次”下让所有学生连续考两场；请开启“允许同科目分批”，并准备分批试卷，或改用普通学校考试')
    # Six shared waves: three common subjects, one primary, two electives.
    dummy = [{'id': i + 1, 'grade_id': 0, 'subject_id': i + 1} for i in range(6)]
    calendar = generate_exam_schedule(dummy, start_date=start_date, sessions=sessions,
                                     excluded_dates=excluded_dates, room=room)
    common_wave = {'语文': 0, '数学': 1, '英语': 2, '外语': 2}
    buckets = defaultdict(list)
    original = {(c['grade_id'], c['subject_id']): c for c in courses}
    for sid, selected in sorted(by_student.items()):
        pair = pairs[sid]
        for course in selected:
            subject = course['subject_id']
            name = names[subject]
            if name in common:
                wave = common_wave[name]
            elif name in primary:
                wave = 3
            else:
                wave = 4 + (pair.index(subject) if needs_batches else colors[subject])
            buckets[wave, course['grade_id'], subject].append(sid)
    result, expanded, assigned = [], [], {}
    for key, (wave, grade, subject) in enumerate(sorted(buckets), start=1):
        course = {**original[grade, subject], 'id': key}
        expanded.append(course)
        assigned[key] = buckets[wave, grade, subject]
        result.append(replace(calendar[wave], course_key=key, grade_id=grade, subject_id=subject))
    return result, expanded, assigned, needs_batches
