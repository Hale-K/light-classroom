"""Small, shared set of configurable exam constraints."""
from collections import defaultdict
from hashlib import sha256
from typing import Annotated, Literal
from pydantic import BaseModel, Field


class ExamRules(BaseModel):
    reference_mode: Literal['auto', 'manual'] = 'auto'
    room_mode: Literal['school', 'gaokao'] = 'school'
    room_seat_limit: Literal[25, 30] = 30
    student_daily_limit: int = Field(default=4, ge=1, le=4)
    min_break_minutes: int = Field(default=0, ge=0, le=180)
    teacher_daily_limit: int = Field(default=4, ge=1, le=8)
    avoid_own_subject: bool = False
    same_subject_same_time: bool = False
    allow_subject_batches: bool = False
    subject_time_slots: dict[Annotated[int, Field(gt=0)], Annotated[str, Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')]] = Field(default_factory=dict, max_length=100)


def exam_seat_capacity(capacity, rules):
    return min(capacity, rules.room_seat_limit) if rules.room_mode == 'gaokao' else capacity


def order_exam_rosters(rosters, rules, exam_id):
    if rules.room_mode != 'gaokao':
        return rosters
    # A repeatable shuffle independent of class order. Shared rosters retain
    # the same ordering across common subjects and repeated previews.
    return {key: sorted(set(ids), key=lambda sid: sha256(f'{exam_id}:{sid}'.encode()).digest())
            for key, ids in rosters.items()}


def minutes(value):
    return int(value[:2]) * 60 + int(value[3:5])


def calendar_violations(schedules, rules, *, group_label='年级', check_daily=True):
    groups = defaultdict(list)
    for s in schedules:
        groups[s.grade_id, s.exam_date].append(s)
    issues = []
    for s in schedules:
        required = rules.subject_time_slots.get(getattr(s, 'subject_id', None))
        if required and s.start_time != required:
            issues.append(f'科目 {s.subject_id} 必须安排在 {required} 开始的场次')
    for (grade, day), rows in groups.items() if check_daily else []:
        rows = sorted({(s.start_time, s.end_time): s for s in rows}.values(), key=lambda s: s.start_time)
        if len(rows) > rules.student_daily_limit:
            issues.append(f'{day} {group_label} {grade} 安排了 {len(rows)} 门考试，超过每日 {rules.student_daily_limit} 门上限')
        for a, b in zip(rows, rows[1:]):
            gap = minutes(b.start_time) - minutes(a.end_time)
            if gap < rules.min_break_minutes:
                issues.append(f'{day} {a.end_time} 至 {b.start_time} 的休息间隔不足 {rules.min_break_minutes} 分钟')
    if rules.same_subject_same_time:
        subject_times = defaultdict(set)
        for s in schedules:
            subject_times[s.subject_id].add((s.exam_date, s.start_time, s.end_time))
        if any(len(times) > 1 for times in subject_times.values()):
            issues.append('同科目在不同年级的考试时间不一致')
    return issues
