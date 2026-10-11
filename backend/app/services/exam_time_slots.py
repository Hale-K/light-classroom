"""Place ordered subjects into their explicitly selected daily sessions."""
from dataclasses import replace
from datetime import timedelta
from app.services.exam_rules import minutes


def apply_subject_time_slots(items, *, start_date, sessions, excluded_dates, rules, unavailable=None):
    if not rules.subject_time_slots and unavailable is None:
        return items
    sessions = sorted(sessions)
    used_preferences = {s.subject_id: rules.subject_time_slots[s.subject_id] for s in items if s.subject_id in rules.subject_time_slots}
    if set(used_preferences.values()) - {start for start, _ in sessions}:
        raise ValueError('指定科目的考试时段已被修改或删除，请重新选择科目时段')
    day, cursor, count, last_end = start_date, 0, 0, None
    result = []
    for item in items:
        while True:
            if (day - start_date).days > 365:
                raise ValueError('一年内没有满足科目时段、禁排日期及考生占用的场次，请调整考试条件')
            if day.weekday() >= 5 or day in excluded_dates:
                day += timedelta(days=1)
                cursor, count, last_end = 0, 0, None
                continue
            eligible = [i for i, (start, _) in enumerate(sessions) if i >= cursor
                        and (not used_preferences.get(item.subject_id) or start == used_preferences[item.subject_id])
                        and (last_end is None or minutes(start) - minutes(last_end) >= rules.min_break_minutes)
                        and (unavailable is None or not unavailable(item, day, start, sessions[i][1]))]
            if eligible and count < rules.student_daily_limit:
                index = eligible[0]
                start, end = sessions[index]
                result.append(replace(item, exam_date=day, start_time=start, end_time=end))
                cursor, count, last_end = index + 1, count + 1, end
                break
            day += timedelta(days=1)
            cursor, count, last_end = 0, 0, None
    return result
