from datetime import date
from time import perf_counter

import pytest

from app.services.scheduling import (
    ExamRoomResource,
    arrange_students,
    arrange_exam_candidates,
    diagnose_staffing_gaps,
    expand_schedule,
    generate_exam_schedule,
    generate_schedule,
    normalize_exam_room_resources,
    repair_class_gaps,
    resolve_exam_candidates,
    validate_schedule_requirements,
)


def test_invigilator_pool_uses_all_active_teachers_but_excludes_school_admins():
    from types import SimpleNamespace
    from app.models.enums import BaseUserRole, UserStatus
    from app.services.scheduling import select_invigilator_ids

    users = [
        SimpleNamespace(id=1, role=BaseUserRole.teacher, status=UserStatus.active),
        SimpleNamespace(id=2, role=BaseUserRole.teacher, status=UserStatus.disabled),
        SimpleNamespace(id=3, role=BaseUserRole.director, status=UserStatus.active),
        SimpleNamespace(id=4, role=BaseUserRole.teacher, status=UserStatus.active),
    ]

    assert select_invigilator_ids(users) == [1, 4]


def test_exam_room_status_follows_resource_and_exam_lifecycle():
    from datetime import date
    from app.services.scheduling import resolve_exam_room_status

    today = date(2026, 8, 24)
    assert resolve_exam_room_status('available', today=today) == 'available'
    assert resolve_exam_room_status('available', selected=True, today=today) == 'selected'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[date(2026, 8, 25)], today=today) == 'scheduled'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[today], today=today) == 'ongoing'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[date(2026, 8, 23)], today=today) == 'completed'
    assert resolve_exam_room_status('maintenance', selected=True, scheduled_dates=[today], today=today) == 'maintenance'
    assert resolve_exam_room_status('disabled', today=today) == 'disabled'


def test_exam_room_resources_are_trimmed_and_duplicate_names_are_rejected():
    rooms = normalize_exam_room_resources([
        ExamRoomResource(name="  实验楼报告厅  ", capacity=120),
        ExamRoomResource(name="高三(1)班教室", capacity=40),
    ])

    assert rooms[0] == ExamRoomResource(name="实验楼报告厅", capacity=120)
    with pytest.raises(ValueError, match="考场名称重复"):
        normalize_exam_room_resources([
            ExamRoomResource(name="备用考场", capacity=30),
            ExamRoomResource(name=" 备用考场 ", capacity=20),
        ])


def test_remaining_gap_reports_the_subject_teacher_conflict_and_staffing_need():
    from app.services.scheduling import ScheduleItem

    items = [
        *[
            ScheduleItem(period=period, weekday=1, class_id=1, teacher_id=period,
                         subject_id=period, assignment_id=period)
            for period in range(1, 6)
        ],
        ScheduleItem(period=7, weekday=1, class_id=1, teacher_id=10,
                     subject_id=8, assignment_id=7),
        ScheduleItem(period=6, weekday=1, class_id=2, teacher_id=10,
                     subject_id=8, assignment_id=8),
    ]

    issues = diagnose_staffing_gaps(items)

    assert issues == [{
        "class_id": 1,
        "subject_id": 8,
        "teacher_id": 10,
        "weekday": 1,
        "gap_period": 6,
        "scheduled_period": 7,
        "blocking_class_id": 2,
        "additional_teachers": 1,
    }]


def test_cross_class_gap_repair_relocates_a_teacher_blocker():
    from app.services.scheduling import ScheduleItem

    items = [
        *[
            ScheduleItem(period=period, weekday=1, class_id=1, teacher_id=period,
                         subject_id=period, assignment_id=period)
            for period in range(1, 6)
        ],
        ScheduleItem(period=7, weekday=1, class_id=1, teacher_id=10,
                     subject_id=7, assignment_id=7),
        ScheduleItem(period=6, weekday=1, class_id=2, teacher_id=10,
                     subject_id=8, assignment_id=8),
    ]

    repaired = repair_class_gaps(items, days=2, periods_per_day=7)

    class_one_monday = sorted(
        item.period for item in repaired if item.class_id == 1 and item.weekday == 1
    )
    assert class_one_monday == [1, 2, 3, 4, 5, 6]
    assert len({(item.class_id, item.weekday, item.period) for item in repaired}) == len(repaired)
    assert len({(item.teacher_id, item.weekday, item.period) for item in repaired}) == len(repaired)


def test_generate_schedule_has_no_teacher_or_class_conflicts():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 4},
        {"id": 3, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
    ]

    result = generate_schedule(assignments, days=5, periods_per_day=8)

    assert result.unplaced == []
    assert len(result.items) == 14
    class_slots = {(item.class_id, item.weekday, item.period) for item in result.items}
    teacher_slots = {(item.teacher_id, item.weekday, item.period) for item in result.items}
    assert len(class_slots) == len(result.items)
    assert len(teacher_slots) == len(result.items)


def test_validate_schedule_requirements_reports_class_capacity_shortage():
    assignments = [
        {"id": 1, "class_id": 7, "subject_id": 1, "teacher_id": 10, "weekly_periods": 3},
        {"id": 2, "class_id": 7, "subject_id": 2, "teacher_id": 11, "weekly_periods": 2},
    ]

    result = validate_schedule_requirements(assignments, days=1, periods_per_day=4)

    assert result.valid is False
    assert [(issue.code, issue.entity_id, issue.requested, issue.capacity) for issue in result.issues] == [
        ("class_capacity_exceeded", 7, 5, 4),
    ]


def test_subject_capacity_shortage_explains_rule_and_suggests_a_valid_limit():
    assignments = [
        {"id": 1, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 8},
    ]

    result = validate_schedule_requirements(
        assignments,
        days=5,
        periods_per_day=8,
        max_same_subject_per_day=1,
    )

    issue = result.issues[0]
    assert issue.code == "subject_capacity_exceeded"
    assert issue.rule_code == "max_same_subject_per_day"
    assert issue.formula == "5 个可排教学日 × 每日最多 1 节 = 5 节"
    assert issue.suggestions[0].field == "max_same_subject_per_day"
    assert issue.suggestions[0].recommended_value == 2
    assert issue.suggestions[1].field == "weekly_periods"
    assert issue.suggestions[1].recommended_value == 5
    assert any(rule.code == "max_same_subject_per_day" and rule.result == 5 for rule in result.rules)


def test_capacity_suggestion_does_not_claim_a_daily_limit_can_solve_an_impossible_week():
    assignments = [
        {"id": index, "class_id": 2, "subject_id": index, "teacher_id": index, "weekly_periods": 8}
        for index in range(1, 10)
    ]

    result = validate_schedule_requirements(
        assignments,
        days=5,
        periods_per_day=8,
        max_class_lessons_per_day=7,
        max_same_subject_per_day=1,
    )

    class_issue = next(issue for issue in result.issues if issue.code == "class_capacity_exceeded")
    assert class_issue.suggestions[0].code == "reduce_class_weekly_load"
    assert class_issue.suggestions[0].field == "class_total_weekly_periods"
    assert class_issue.suggestions[0].recommended_value == 40


def test_generate_schedule_repairs_a_single_blocking_lesson():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 3, "teacher_id": 1, "weekly_periods": 2},
        {"id": 2, "class_id": 2, "subject_id": 2, "teacher_id": 3, "weekly_periods": 2},
        {"id": 3, "class_id": 1, "subject_id": 2, "teacher_id": 2, "weekly_periods": 1},
        {"id": 4, "class_id": 2, "subject_id": 1, "teacher_id": 2, "weekly_periods": 2},
    ]

    result = generate_schedule(assignments, days=2, periods_per_day=2)

    assert result.unplaced == []
    assert len(result.items) == 7
    assert len({(item.class_id, item.weekday, item.period) for item in result.items}) == 7
    assert len({(item.teacher_id, item.weekday, item.period) for item in result.items}) == 7


def test_generate_schedule_prioritizes_full_schedule_over_teacher_gap():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 1, "weekly_periods": 4}],
        days=2,
        periods_per_day=2,
        avoid_consecutive_teacher_lessons=True,
    )

    assert result.unplaced == []
    assert len(result.items) == 4


def test_generate_schedule_accepts_a_registered_strategy_combination():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 4},
        {"id": 2, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 4},
        {"id": 3, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 3},
    ]

    result = generate_schedule(
        assignments,
        strategy_codes=["class_compact", "teacher_friendly", "daily_balance"],
    )

    assert result.unplaced == []
    assert len(result.items) == 11
    assert len({(item.class_id, item.weekday, item.period) for item in result.items}) == 11
    assert len({(item.teacher_id, item.weekday, item.period) for item in result.items}) == 11


def test_generate_schedule_preserves_required_weekly_periods():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 6},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 3},
    ]

    result = generate_schedule(assignments, days=5, periods_per_day=8)

    assert sum(item.assignment_id == 1 for item in result.items) == 6
    assert sum(item.assignment_id == 2 for item in result.items) == 3


def test_generate_schedule_avoids_same_subject_at_same_period_on_consecutive_days():
    assignments = [
        {"id": subject_id, "class_id": 1, "teacher_id": None,
         "subject_id": subject_id, "weekly_periods": 5}
        for subject_id in range(1, 9)
    ]

    result = generate_schedule(assignments, random_seed=20260824)

    for subject_id in range(1, 9):
        periods_by_day = {
            item.weekday: item.period
            for item in result.items
            if item.subject_id == subject_id
        }
        consecutive_repeats = sum(
            periods_by_day.get(day) == periods_by_day.get(day + 1)
            for day in range(1, 5)
        )
        assert consecutive_repeats == 0


def test_generate_schedule_random_tiebreak_is_repeatable_with_the_same_seed():
    assignments = [
        {"id": subject_id, "class_id": 1, "teacher_id": None,
         "subject_id": subject_id, "weekly_periods": 3}
        for subject_id in range(1, 7)
    ]

    first = generate_schedule(assignments, random_seed=11)
    repeated = generate_schedule(assignments, random_seed=11)
    different = generate_schedule(assignments, random_seed=29)
    positions = lambda result: [(item.subject_id, item.weekday, item.period) for item in result.items]

    assert positions(first) == positions(repeated)
    assert positions(first) != positions(different)


def test_generate_schedule_respects_custom_forbidden_slots_and_daily_limit():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 5},
    ]

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=8,
        forbidden_slots={(1, 1), (3, 8)},
        max_class_lessons_per_day=2,
        max_same_subject_per_day=1,
    )

    assert result.unplaced == []
    assert all((item.weekday, item.period) not in {(1, 1), (3, 8)} for item in result.items)
    assert all(sum(entry.class_id == 1 and entry.weekday == day for entry in result.items) <= 2 for day in range(1, 6))
    assert all(
        sum(entry.class_id == 1 and entry.subject_id == subject and entry.weekday == day for entry in result.items) <= 1
        for subject in (1, 2)
        for day in range(1, 6)
    )


def test_generate_schedule_handles_school_scale_without_timing_out():
    periods = [5, 5, 5, 3, 3, 3, 2, 2, 2]
    teacher_pools = [14, 14, 14, 10, 10, 10, 8, 8, 8]
    assignments = [
        {
            "id": (class_id - 1) * 9 + subject_index + 1,
            "class_id": class_id,
            "subject_id": subject_index + 1,
            "teacher_id": subject_index * 100 + (class_id - 1) % teacher_pools[subject_index] + 1,
            "weekly_periods": periods[subject_index],
        }
        for class_id in range(1, 41)
        for subject_index in range(9)
    ]

    started = perf_counter()
    result = generate_schedule(
        assignments,
        max_class_lessons_per_day=7,
        max_teacher_lessons_per_day=6,
        max_same_subject_per_day=1,
    )
    elapsed = perf_counter() - started

    assert len(result.items) == 1200
    assert result.unplaced == []
    assert elapsed < 1.5


def test_expand_schedule_maps_weekday_to_calendar_date():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 2}],
        days=5,
        periods_per_day=8,
    )

    dated = expand_schedule(result.items, date(2026, 8, 24))

    assert all(item.lesson_date == date(2026, 8, 24 + item.weekday - 1) for item in dated)


def test_expand_schedule_requires_monday():
    with pytest.raises(ValueError, match="周一"):
        expand_schedule([], date(2026, 8, 25))


def test_arrange_students_rejects_insufficient_capacity():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    with pytest.raises(ValueError, match="容量"):
        arrange_students(students, rows=2, cols=2, rule="roster")


def test_arrange_students_uses_snake_row_direction():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(students, rows=2, cols=3, rule="snake")

    assert [(seat.row, seat.col, seat.student_id) for seat in seats] == [
        (1, 1, 1), (1, 2, 2), (1, 3, 3),
        (2, 3, 4), (2, 2, 5), (2, 1, 6),
    ]


def test_arrange_students_gender_rule_alternates_when_possible():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1},
        {"id": 2, "gender": "male", "roster_order": 2},
        {"id": 3, "gender": "female", "roster_order": 3},
        {"id": 4, "gender": "female", "roster_order": 4},
    ]

    seats = arrange_students(students, rows=2, cols=2, rule="gender")

    assert [seat.student_id for seat in seats] == [1, 3, 2, 4]


def test_arrange_students_random_rule_is_repeatable_with_seed():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    first = arrange_students(students, rows=2, cols=3, rule="random", seed=2026)
    second = arrange_students(students, rows=2, cols=3, rule="random", seed=2026)

    assert [seat.student_id for seat in first] == [seat.student_id for seat in second]


def test_arrange_students_places_priority_students_in_front():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(students, rows=2, cols=3, rule="roster", front_student_ids={5, 6})

    assert [seat.student_id for seat in seats[:2]] == [5, 6]


def _seat_pos(seats, student_id: int) -> tuple[int, int]:
    seat = next(s for s in seats if s.student_id == student_id)
    return (seat.row, seat.col)


def _are_adjacent(seats, a: int, b: int) -> bool:
    ra, ca = _seat_pos(seats, a)
    rb, cb = _seat_pos(seats, b)
    return max(abs(ra - rb), abs(ca - cb)) == 1


def test_arrange_students_height_pairing_alternates_tall_and_short():
    students = [
        {"id": i, "gender": "male", "roster_order": i, "height_cm": h}
        for i, h in enumerate([160, 180, 165, 178, 170, 172], start=1)
    ]

    seats = arrange_students(students, rows=2, cols=3, order="roster", layout="normal", pairing="height")

    order_of_ids = [seat.student_id for seat in seats]
    # 相邻座位应为“一高一矮”，不允许出现连续递增/递减的高低走势
    heights = {s["id"]: s["height_cm"] for s in students}
    seq = [heights[i] for i in order_of_ids]
    monotonic = all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)) or \
        all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1))
    assert not monotonic


def test_arrange_students_separation_pairs_are_not_adjacent():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(
        students, rows=2, cols=3, order="roster", layout="normal",
        separation_pairs=[[1, 2]],
    )

    assert not _are_adjacent(seats, 1, 2)


def test_arrange_students_adjacency_pairs_are_adjacent():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(
        students, rows=1, cols=6, order="roster", layout="normal",
        adjacency_pairs=[[1, 3]],
    )

    assert _are_adjacent(seats, 1, 3)


def test_arrange_students_score_rule_orders_descending_with_missing_last():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1, "exam_score": 88.0},
        {"id": 2, "gender": "male", "roster_order": 2, "exam_score": 70.0},
        {"id": 3, "gender": "male", "roster_order": 3, "exam_score": 95.0},
        {"id": 4, "gender": "male", "roster_order": 4},  # 无成绩
    ]

    seats = arrange_students(students, rows=1, cols=4, order="score", layout="normal")

    assert [seat.student_id for seat in seats] == [3, 1, 2, 4]


def test_arrange_students_score_puts_tallest_on_edges():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1, "exam_score": 90.0, "height_cm": 160},
        {"id": 2, "gender": "male", "roster_order": 2, "exam_score": 80.0, "height_cm": 180},
        {"id": 3, "gender": "male", "roster_order": 3, "exam_score": 85.0, "height_cm": 150},
    ]

    seats = arrange_students(students, rows=1, cols=3, order="score", layout="normal")

    col_of = {seat.student_id: seat.col for seat in seats}
    # 同一行三列：个子最高的落侧边，最矮的居中
    assert col_of[2] in (1, 3)
    assert col_of[3] == 2


def test_generate_exam_schedule_skips_weekends():
    papers = [{"id": i, "subject_id": i, "grade_id": 1, "teacher_id": i} for i in range(1, 6)]

    items = generate_exam_schedule(papers, start_date=date(2026, 8, 28))

    assert [item.exam_date.isoformat() for item in items] == [
        "2026-08-28", "2026-08-28", "2026-08-31", "2026-08-31", "2026-09-01",
    ]


def test_generate_exam_schedule_assigns_available_invigilators():
    papers = [
        {"id": 1, "subject_id": 1, "grade_id": 1, "teacher_id": 10},
        {"id": 2, "subject_id": 2, "grade_id": 1, "teacher_id": 11},
    ]

    items = generate_exam_schedule(papers, start_date=date(2026, 8, 24), teacher_ids=[10, 11, 12])

    assert items[0].invigilator_id != 10
    assert items[1].invigilator_id != 11
    assert items[0].session_index != items[1].session_index


def test_generate_exam_schedule_skips_custom_excluded_dates():
    papers = [{"id": i, "subject_id": i, "grade_id": 1, "teacher_id": i} for i in range(1, 5)]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 8, 24),
        excluded_dates={date(2026, 8, 25)},
    )

    assert {item.exam_date for item in items} == {date(2026, 8, 24), date(2026, 8, 26)}


def test_312_exam_schedule_uses_three_day_gaokao_template():
    subject_names = {
        1: "语文", 2: "数学", 3: "英语", 4: "物理", 5: "化学",
        6: "生物", 7: "政治", 8: "历史", 9: "地理",
    }
    papers = [
        {"id": subject_id, "subject_id": subject_id, "grade_id": 3, "teacher_id": subject_id}
        for subject_id in subject_names
    ]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 6, 7),
        mode="3+1+2",
        subject_names=subject_names,
    )

    by_subject = {subject_names[item.subject_id]: item for item in items}
    assert {item.exam_date for item in items} == {
        date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10),
    }
    assert (by_subject["语文"].exam_date, by_subject["语文"].start_time) == (date(2026, 6, 8), "09:00")
    assert (by_subject["数学"].exam_date, by_subject["数学"].start_time) == (date(2026, 6, 8), "15:00")
    assert (by_subject["物理"].exam_date, by_subject["物理"].start_time) == (date(2026, 6, 9), "09:00")
    assert (by_subject["历史"].exam_date, by_subject["历史"].start_time) == (date(2026, 6, 9), "09:00")
    assert (by_subject["英语"].exam_date, by_subject["英语"].start_time) == (date(2026, 6, 9), "15:00")
    assert (by_subject["化学"].exam_date, by_subject["化学"].start_time) == (date(2026, 6, 10), "08:30")
    assert (by_subject["地理"].exam_date, by_subject["地理"].start_time) == (date(2026, 6, 10), "11:00")
    assert (by_subject["政治"].exam_date, by_subject["政治"].start_time) == (date(2026, 6, 10), "14:30")
    assert (by_subject["生物"].exam_date, by_subject["生物"].start_time) == (date(2026, 6, 10), "17:00")


def test_312_exam_schedule_runs_same_subject_for_multiple_grades_in_parallel():
    papers = [
        {"id": 1, "subject_id": 1, "grade_id": 1, "teacher_id": 10},
        {"id": 2, "subject_id": 1, "grade_id": 2, "teacher_id": 11},
        {"id": 3, "subject_id": 2, "grade_id": 1, "teacher_id": 12},
        {"id": 4, "subject_id": 2, "grade_id": 2, "teacher_id": 13},
    ]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文", 2: "数学"},
    )

    chinese = [item for item in items if item.subject_id == 1]
    mathematics = [item for item in items if item.subject_id == 2]
    assert len({(item.exam_date, item.start_time, item.end_time) for item in chinese}) == 1
    assert len({(item.exam_date, item.start_time, item.end_time) for item in mathematics}) == 1
    assert chinese[0].session_index != mathematics[0].session_index


def test_exam_candidate_arrangement_assigns_every_student_to_a_room_and_seat():
    schedules = generate_exam_schedule(
        [
            {"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90},
            {"id": 102, "subject_id": 2, "grade_id": 3, "teacher_id": 91},
        ],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文", 2: "数学"},
    )

    result = arrange_exam_candidates(
        schedules,
        candidate_ids_by_paper={101: [1, 2, 3, 4, 5], 102: [1, 2, 3, 4, 5]},
        rooms=[ExamRoomResource(name="高三01考场", capacity=3), ExamRoomResource(name="高三02考场", capacity=3)],
        teacher_ids=[10, 11, 12, 13],
        invigilators_per_room=1,
    )

    assert len(result.seats) == 10
    assert len(result.rooms) == 4
    assert {(seat.paper_id, seat.student_id) for seat in result.seats} == {
        (paper_id, student_id) for paper_id in (101, 102) for student_id in range(1, 6)
    }
    assert all(1 <= seat.seat_no <= 3 for seat in result.seats)
    assert len({(room.exam_date, room.session_index, room.room_name) for room in result.rooms}) == len(result.rooms)


def test_exam_candidate_arrangement_rejects_room_capacity_shortage():
    schedules = generate_exam_schedule(
        [{"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90}],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文"},
    )

    with pytest.raises(ValueError, match="考场容量不足"):
        arrange_exam_candidates(
            schedules,
            candidate_ids_by_paper={101: [1, 2, 3, 4, 5]},
            rooms=[ExamRoomResource(name="高三01考场", capacity=4)],
            teacher_ids=[10],
            invigilators_per_room=1,
        )


def test_exam_candidate_arrangement_skips_teacher_on_leave_for_the_slot():
    schedules = generate_exam_schedule(
        [{"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90}],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文"},
    )
    slot = (schedules[0].exam_date, schedules[0].session_index)

    result = arrange_exam_candidates(
        schedules,
        candidate_ids_by_paper={101: [1]},
        rooms=[ExamRoomResource(name="高三01考场", capacity=40)],
        teacher_ids=[10, 11],
        unavailable_teacher_slots={10: {slot}},
        invigilators_per_room=1,
    )

    assert result.rooms[0].invigilator_ids == (11,)


def test_resolve_312_exam_candidates_uses_grade_roster_and_confirmed_choices():
    papers = [
        {"id": 101, "subject_id": 1, "grade_id": 3},
        {"id": 104, "subject_id": 4, "grade_id": 3},
        {"id": 108, "subject_id": 8, "grade_id": 3},
    ]

    result = resolve_exam_candidates(
        papers,
        student_ids_by_grade={3: [1, 2, 3, 4]},
        selected_subject_ids_by_student={
            1: {4, 5, 6},
            2: {4, 7, 9},
            3: {8, 5, 6},
            4: {8, 7, 9},
        },
        subject_names={1: "语文", 4: "物理", 8: "历史"},
    )

    assert result[101] == [1, 2, 3, 4]
    assert result[104] == [1, 2]
    assert result[108] == [3, 4]
