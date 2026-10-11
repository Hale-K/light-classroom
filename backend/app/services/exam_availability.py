"""Persist recurring unavailable windows alongside legacy date/session keys."""
import re

WEEKLY_WINDOW = re.compile(r'^weekly#([1-7])#([0-2]\d:[0-5]\d)#([0-2]\d:[0-5]\d)$')


def parse_weekly_window(value):
    match = WEEKLY_WINDOW.fullmatch(value)
    if not match:
        return None
    weekday, start, end = match.groups()
    if start >= end or start[:2] > '23' or end[:2] > '23':
        return None
    return int(weekday), start, end


def teacher_time_blocked(setting, schedule):
    if not setting:
        return False
    if not setting.enabled:
        return True
    if setting.leave_start and setting.leave_end and setting.leave_start <= schedule.exam_date <= setting.leave_end:
        return True
    for value in setting.unavailable_slots:
        if value == f'{schedule.exam_date}#{schedule.session_index}':
            return True
        window = parse_weekly_window(value)
        if window and window[0] == schedule.exam_date.isoweekday() and schedule.start_time < window[2] and window[1] < schedule.end_time:
            return True
    return False
