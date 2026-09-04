import pytest

from app.services.scheduling.rules import (
    RuleGroupDocument,
    RuleTarget,
    RuleEvaluationSummary,
    RuleEvaluationResult,
    blocking_rule_results,
    compile_rule_group,
    evaluate_rule_group,
    generation_class_slot_allowed_subjects,
    generation_global_forbidden_slots,
    generation_class_required_subject_slots,
    generation_early_subject_ids,
    generation_early_subject_prefs,
    generation_gap_fill_late_subjects,
    generation_evening_parity_pairs,
    generation_daytime_parity_pairs,
    generation_subject_allowed_slots,
    generation_subject_forbidden_slots,
    generation_slot_teacher_balance_scope,
    generation_teacher_daily_limits,
    generation_teacher_forbidden_slots,
    generation_teacher_required_evening_weekdays,
    generation_class_slot_required_teachers,
    generation_gap_free_groups,
    generation_class_gap_free_weekdays,
    generation_evening_free_days,
    generation_evening_self_study_candidates,
    parse_stored_rule_groups,
    pick_rule_group,
    dump_stored_rule_groups,
)
from app.models.enums import WeekParity


def test_all_non_passing_hard_rules_block_generation_instead_of_using_a_code_allowlist():
    summary = RuleEvaluationSummary(
        valid=False,
        compiled=False,
        schedule_available=True,
        schedule_item_count=1,
        results=[
            RuleEvaluationResult(
                rule_id="R-prep",
                code="slot_forbidden",
                title="备课禁排",
                priority="hard",
                status="fail",
                violation_count=1,
                message="发现 1 个课位违反规则",
            ),
            RuleEvaluationResult(
                rule_id="R-manual",
                code="manual_review",
                title="未解析要求",
                priority="hard",
                status="unresolved",
                message="规则无法编译",
            ),
            RuleEvaluationResult(
                rule_id="R-soft",
                code="teacher_preferred_weekdays",
                title="教师偏好",
                priority="soft",
                status="fail",
                violation_count=1,
                message="有 1 节课未落在偏好星期",
            ),
        ],
    )

    assert [item.rule_id for item in blocking_rule_results(summary)] == ["R-prep", "R-manual"]
from app.services.scheduling import ScheduleItem
from app.services.scheduling.cpsat import solve_daytime_cpsat


def _group(*rules: dict) -> RuleGroupDocument:
    return RuleGroupDocument(
        id="grade-1-rules",
        name="高一组排课规则",
        academic_year="2026-2027",
        term="1",
        rules=list(rules),
    )


def test_compile_rejects_unknown_rule_code_instead_of_guessing_from_title():
    group = _group({
        "id": "R-unknown",
        "title": "一条自然语言要求",
        "code": "some_text_rule",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
    })

    with pytest.raises(ValueError, match="未知规则编码"):
        compile_rule_group(group)


def test_teacher_daily_limit_is_evaluated_from_typed_parameters():
    group = _group({
        "id": "R-teacher-limit",
        "title": "教师每日最多三节",
        "code": "teacher_daily_limit",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7]},
        "weekdays": [1, 2, 3, 4, 5],
        "params": {"max_lessons_per_day": 3},
    })
    items = [
        ScheduleItem(assignment_id=index, class_id=index, subject_id=1, teacher_id=7,
                     weekday=1, period=index,)
        for index in range(1, 5)
    ]

    result = evaluate_rule_group(group, items, schedule_available=True)

    assert result.valid is False
    assert result.results[0].status == "fail"
    assert result.results[0].violation_count == 1


def test_subject_consecutive_requires_a_real_block_for_each_target_class():
    group = _group({
        "id": "R-subject-block",
        "title": "数学每周至少一天连堂",
        "code": "subject_consecutive",
        "priority": "hard",
        "target": {"type": "subject", "ids": [3]},
        "weekdays": [1, 2, 3, 4, 5],
        "params": {"minimum_block_length": 2, "minimum_days": 1},
    })
    items = [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=3, teacher_id=7, weekday=1, period=2),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=3, teacher_id=7, weekday=1, period=3),
    ]

    result = evaluate_rule_group(group, items, schedule_available=True)

    assert result.valid is True
    assert result.results[0].status == "pass"
    assert result.results[0].metrics["satisfied_days"] == 1


def test_subject_consecutive_fails_when_target_subject_is_absent_from_schedule():
    group = _group({
        "id": "R-subject-block",
        "title": "数学每周至少一天连堂",
        "code": "subject_consecutive",
        "priority": "hard",
        "target": {"type": "subject", "ids": [3]},
        "params": {"minimum_block_length": 2, "minimum_days": 1},
    })
    items = [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=4, teacher_id=7, weekday=1, period=2),
    ]

    result = evaluate_rule_group(group, items, schedule_available=True)

    assert result.valid is False
    assert result.results[0].violation_count == 1


def test_rules_are_not_reported_as_pass_when_no_schedule_exists():
    group = _group({
        "id": "R-subject-block",
        "title": "数学每周至少一天连堂",
        "code": "subject_consecutive",
        "priority": "hard",
        "target": {"type": "subject", "ids": [3]},
        "params": {"minimum_block_length": 2, "minimum_days": 1},
    })

    result = evaluate_rule_group(group, [], schedule_available=False)

    assert result.valid is False
    assert result.results[0].status == "not_run"


def test_teacher_forbidden_slots_accepts_sparse_weekday_period_matrix():
    group = _group({
        "id": "R12",
        "title": "毛宇莹不可用课位",
        "code": "teacher_forbidden_slots",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7]},
        "params": {"forbidden_slots": [
            {"weekday": 1, "periods": [1, 3, 5]},
            {"weekday": 2, "periods": [1, 5, 7, 8]},
            {"weekday": 3, "periods": [1, 2, 5]},
        ]},
    })

    compiled = compile_rule_group(group)
    result = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=3),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=4),
    ])

    assert compiled[0].status == "ready"
    assert result.results[0].status == "fail"
    assert result.results[0].violation_count == 1
    assert generation_teacher_forbidden_slots(group) == {
        7: {(1, 1), (1, 3), (1, 5), (2, 1), (2, 5), (2, 7), (2, 8), (3, 1), (3, 2), (3, 5)},
    }


def test_r16_chu_guangqing_cannot_take_period_one():
    group = _group({
        "id": "R16",
        "title": "褚光庆不排第1节",
        "code": "teacher_forbidden_slots",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [701]},
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "periods": [1],
        "period_scope": "regular",
    })
    compiled = compile_rule_group(group)
    ok = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=4, subject_id=5, teacher_id=701, weekday=1, period=2),
        ScheduleItem(assignment_id=2, class_id=5, subject_id=5, teacher_id=701, weekday=6, period=3),
        ScheduleItem(assignment_id=3, class_id=4, subject_id=5, teacher_id=701, weekday=2, period=10),
    ])
    banned = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=4, subject_id=5, teacher_id=701, weekday=6, period=1),
    ])

    assert compiled[0].status == "ready"
    assert generation_teacher_forbidden_slots(group) == {
        701: {(day, 1) for day in range(1, 8)},
    }
    assert ok.results[0].status == "pass"
    assert banned.results[0].status == "fail"
    assert banned.results[0].violation_count == 1


def test_r17_head_teachers_cannot_take_period_five():
    from app.services.scheduling.rules import generation_teacher_class_forbidden_slots

    group = _group({
        "id": "R17-01",
        "title": "第五节不排班主任",
        "code": "teacher_forbidden_slots",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7, 8]},
        "weekdays": [1, 2, 3, 4, 5, 6, 7],
        "periods": [5],
        "period_scope": "regular",
        "params": {"own_head_class_only": True},
    })
    # 7=A班(10)班主任，8=B班(12)班主任；11 是他班
    heads = {10: 7, 11: 9, 12: 8}
    ok = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=4),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=2, teacher_id=9, weekday=1, period=5),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=3),
    ], class_head_teacher_ids=heads)
    # 班主任 7 在他班 11 上第5节：允许
    other_class_p5 = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=5),
    ], class_head_teacher_ids=heads)
    # 班主任 7 在本班 10 上第5节：禁止
    own_class_p5 = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=5),
    ], class_head_teacher_ids=heads)
    saturday = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=12, subject_id=1, teacher_id=8, weekday=6, period=5),
    ], class_head_teacher_ids=heads)

    assert compile_rule_group(group)[0].status == "ready"
    assert generation_teacher_forbidden_slots(group) == {}
    assert generation_teacher_class_forbidden_slots(group, heads) == {
        (7, 10): {(day, 5) for day in range(1, 8)},
        (8, 12): {(day, 5) for day in range(1, 8)},
    }
    assert ok.results[0].status == "pass"
    assert other_class_p5.results[0].status == "pass"
    assert own_class_p5.results[0].status == "fail"
    assert saturday.results[0].status == "fail"


def test_manual_review_rules_stay_manual_and_never_block_generation():
    group = _group({
        "id": "R09",
        "title": "王璐跨年级体育课位",
        "code": "manual_review",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
    })

    compiled = compile_rule_group(group)
    result = evaluate_rule_group(group, [], schedule_available=False)

    assert compiled[0].status == "ready"
    assert result.results[0].status == "manual"
    assert result.valid is True
    assert blocking_rule_results(result) == []


def test_subject_slot_forbidden_rules_feed_the_generator():
    group = _group(
        {
            "id": "R01-01",
            "title": "语文备课时段禁排",
            "code": "slot_forbidden",
            "priority": "hard",
            "target": {"type": "subject", "ids": [12]},
            "weekdays": [1],
            "periods": [6, 7],
        },
        {
            "id": "R01-soft",
            "title": "软性禁排不进算法",
            "code": "slot_forbidden",
            "priority": "soft",
            "target": {"type": "subject", "ids": [27]},
            "weekdays": [2],
            "periods": [6],
        },
    )

    assert generation_subject_forbidden_slots(group) == {12: {(1, 6), (1, 7)}}


def test_slot_forbidden_multi_target_feeds_the_generator():
    group = _group(
        {
            "id": "SF-teacher",
            "title": "教师禁排",
            "code": "slot_forbidden",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [101]},
            "weekdays": [3],
            "periods": [5],
        },
        {
            "id": "SF-class",
            "title": "班级禁排",
            "code": "slot_forbidden",
            "priority": "hard",
            "target": {"type": "class", "ids": [627]},
            "weekdays": [1, 2],
            "periods": [8, 9],
        },
        {
            "id": "SF-global",
            "title": "全局禁排",
            "code": "slot_forbidden",
            "priority": "hard",
            "target": {"type": "global", "ids": []},
            "weekdays": [5],
            "periods": [7],
        },
    )

    assert generation_teacher_forbidden_slots(group) == {101: {(3, 5)}}
    assert generation_class_slot_allowed_subjects(group) == {
        627: {(1, 8): set(), (1, 9): set(), (2, 8): set(), (2, 9): set()},
    }
    assert generation_global_forbidden_slots(group) == {(5, 7)}


def test_subject_allowed_slots_rules_feed_the_generator():
    group = _group({
        "id": "R08-01",
        "title": "体育允许课位",
        "code": "subject_allowed_slots",
        "priority": "hard",
        "target": {"type": "subject", "ids": [30]},
        "weekdays": [2, 4],
        "periods": [3, 4],
    })

    assert generation_subject_allowed_slots(group) == {30: {(2, 3), (2, 4), (4, 3), (4, 4)}}


def test_teacher_daily_limit_rules_feed_the_generator_with_the_strictest_limit():
    group = _group(
        {
            "id": "R04-a",
            "title": "工作日教师负荷",
            "code": "teacher_daily_limit",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [7, 8]},
            "params": {"max_lessons_per_day": 3},
        },
        {
            "id": "R04-b",
            "title": "更严格的补充规则",
            "code": "teacher_daily_limit",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [7]},
            "params": {"max_lessons_per_day": 2},
        },
    )

    assert generation_teacher_daily_limits(group) == {7: 2, 8: 3}


def test_teacher_daily_limit_subject_target_expands_to_teachers():
    """学科目标：限制任教该学科教师的全天负荷；未选学科的教师不受限。"""
    group = _group(
        {
            "id": "R04-subj",
            "title": "非体育学科每日上限",
            "code": "teacher_daily_limit",
            "priority": "hard",
            "target": {"type": "subject", "ids": [12, 27]},
            "params": {"max_lessons_per_day": 3},
        },
    )
    assert generation_teacher_daily_limits(
        group,
        teachers_by_subject={12: [100, 101], 27: [101], 30: [200]},
    ) == {100: 3, 101: 3}


def test_multi_class_teacher_evening_lessons_follow_class_cycle():
    group = _group({
        "id": "R15",
        "title": "多班教师晚课轮转",
        "code": "teacher_multi_class_evening_adjacent",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7]},
        "period_scope": "evening",
        "params": {"minimum_class_count": 2},
    })
    rotated = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=9),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=9),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=2),
    ])
    # 中间空一天仍算轮转：周一 10 班、周三 11 班
    with_hole = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=9),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=3, period=9),
    ])
    three = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=9),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=9),
        ScheduleItem(assignment_id=3, class_id=12, subject_id=1, teacher_id=7, weekday=3, period=9),
    ])
    repeated_before_cycle = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=9),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=9),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=9),
    ])

    assert rotated.results[0].status == "pass"
    assert rotated.results[0].violation_count == 0
    assert with_hole.results[0].status == "pass"
    assert with_hole.results[0].violation_count == 0
    assert three.results[0].status == "pass"
    assert three.results[0].metrics["checked_teachers"] == 1
    assert repeated_before_cycle.results[0].status == "fail"
    assert repeated_before_cycle.results[0].violation_count == 1


def test_r15_skips_teachers_with_evening_weekday_limits():
    from app.services.scheduling.rules import generation_r15_exempt_teacher_ids

    group = _group(
        {
            "id": "R15",
            "title": "多班教师晚课轮转",
            "code": "teacher_multi_class_evening_adjacent",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [716, 7]},
            "period_scope": "evening",
            "weekdays": [1, 2, 3, 4, 5],
            "params": {"minimum_class_count": 2},
        },
        {
            "id": "R14",
            "title": "屈金周一周四晚课都要上",
            "code": "teacher_forbidden_slots",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [716]},
            "weekdays": [2, 3, 5, 6],
            "periods": [10],
            "period_scope": "evening",
            "params": {"require_weekdays": [1, 4]},
        },
    )
    assert generation_r15_exempt_teacher_ids(group) == {716}
    result = evaluate_rule_group(
        group,
        [
            ScheduleItem(assignment_id=1, class_id=2, subject_id=25, teacher_id=716, weekday=1, period=10),
            ScheduleItem(assignment_id=2, class_id=4, subject_id=25, teacher_id=716, weekday=4, period=10),
            ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=10),
            ScheduleItem(assignment_id=4, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=10),
            ScheduleItem(assignment_id=5, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=10),
        ],
        evening_start_period=10,
    )
    r15 = next(item for item in result.results if item.rule_id == "R15")
    assert r15.status == "fail"
    assert r15.violation_count == 1
    assert r15.metrics["checked_teachers"] == 1


def test_class_allowed_subjects_only_checks_configured_days_and_periods():
    group = _group({
        "id": "R18",
        "title": "10班晚间活动课限制",
        "code": "class_allowed_subjects",
        "priority": "hard",
        "target": {"type": "class", "ids": [10]},
        "weekdays": [1, 2],
        "periods": [8, 9],
        "params": {"allowed_subject_ids": [20, 21, 22]},
    })
    result = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=99, teacher_id=7, weekday=1, period=1),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=20, teacher_id=7, weekday=1, period=8),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=99, teacher_id=7, weekday=2, period=9),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=99, teacher_id=7, weekday=3, period=8),
    ])

    assert result.results[0].status == "fail"
    assert result.results[0].violation_count == 1
    assert result.results[0].metrics["checked_items"] == 2


def test_class_allowed_subjects_empty_slots_are_optional():
    """「只可以排」= 可空；若排课则科目必须在允许名单内。"""
    group = _group({
        "id": "R18",
        "title": "10班周一周二第8、9节仅活动课",
        "code": "class_allowed_subjects",
        "priority": "hard",
        "target": {"type": "class", "ids": [10]},
        "weekdays": [1, 2],
        "periods": [8, 9],
        "params": {"allowed_subject_ids": [20, 21, 22], "require_occupied_slots": False},
    })
    empty = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=1),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=1, period=8),
    ])
    occupied_ok = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=20, teacher_id=7, weekday=1, period=8),
    ])
    occupied_bad = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=8),
    ])

    assert empty.results[0].status == "pass"
    assert empty.results[0].violation_count == 0
    assert generation_class_required_subject_slots(group) == {}
    assert occupied_ok.results[0].status == "pass"
    assert occupied_bad.results[0].status == "fail"


def test_class_gap_free_weekday_pack_ignores_narrow_periods_filter():
    """「第1～7节」被存成 periods=[1] 时，仍应按 1～7 是否都有课来校验。"""
    group = _group({
        "id": "R04-pack",
        "title": "工作日班级1至7节无空堂",
        "code": "class_gap_free",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
        "weekdays": [1, 2, 3, 4, 5],
        "periods": [1],
        "period_scope": "regular",
        "week_parity": "all",
    })
    full = [
        ScheduleItem(assignment_id=p, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=p)
        for p in range(1, 8)
    ]
    hole = [item for item in full if item.period != 5]
    ok = evaluate_rule_group(group, full, evening_start_period=10)
    bad = evaluate_rule_group(group, hole, evening_start_period=10)
    assert ok.results[0].status == "pass"
    assert bad.results[0].status == "fail"
    assert bad.results[0].violation_count == 1


def test_class_gap_free_saturday_requires_periods_1_to_7_on_both_parities():
    group = _group({
        "id": "R03",
        "title": "周六班级1至7节无空堂",
        "code": "class_gap_free",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
        "weekdays": [6],
        "period_scope": "regular",
        "week_parity": "all",
    })
    full = [
        ScheduleItem(assignment_id=p, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=p)
        for p in range(1, 8)
    ]
    late_block = [item for item in full if item.period != 1]
    odd_only_p3 = [
        item if item.period != 3 else ScheduleItem(
            assignment_id=3, class_id=10, subject_id=1, teacher_id=7,
            weekday=6, period=3, week_parity=WeekParity.odd,
        )
        for item in full
    ]
    ok = evaluate_rule_group(group, full, evening_start_period=10)
    bad_late = evaluate_rule_group(group, late_block, evening_start_period=10)
    bad_odd = evaluate_rule_group(group, odd_only_p3, evening_start_period=10)
    assert ok.results[0].status == "pass"
    assert bad_late.results[0].status == "fail"
    assert bad_odd.results[0].status == "fail"


def test_generation_class_gap_free_weekdays_unions_pack_rules():
    group = _group(
        {
            "id": "R04-pack",
            "title": "工作日班级1至7节无空堂",
            "code": "class_gap_free",
            "priority": "hard",
            "target": {"type": "global", "ids": []},
            "weekdays": [1, 2, 3, 4, 5],
        },
        {
            "id": "R03",
            "title": "周六班级1至7节无空堂",
            "code": "class_gap_free",
            "priority": "hard",
            "target": {"type": "global", "ids": []},
            "weekdays": [6],
        },
    )
    assert generation_class_gap_free_weekdays(group) == [1, 2, 3, 4, 5, 6]


def test_class_slot_pattern_accepts_either_morning_afternoon_direction():
    group = _group({
        "id": "R08-02",
        "title": "体育每班上午下午各一节",
        "code": "class_slot_pattern",
        "priority": "hard",
        "target": {"type": "subject", "ids": [8]},
        "params": {
            "alternatives": [
                [
                    {"weekdays": [2], "periods": [3, 4], "count": 1},
                    {"weekdays": [4], "periods": [6, 7], "count": 1},
                ],
                [
                    {"weekdays": [2], "periods": [6, 7], "count": 1},
                    {"weekdays": [4], "periods": [3, 4], "count": 1},
                ],
            ]
        },
    })
    items = [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=8, teacher_id=7, weekday=2, period=6),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=8, teacher_id=7, weekday=4, period=3),
    ]

    result = evaluate_rule_group(group, items, schedule_available=True)

    assert result.valid is True
    assert result.results[0].status == "pass"
    assert result.results[0].metrics["matched_alternative"] == 2


def test_class_slot_pattern_rejects_two_lessons_in_the_same_part():
    group = _group({
        "id": "R08-02",
        "title": "体育每班上午下午各一节",
        "code": "class_slot_pattern",
        "priority": "hard",
        "target": {"type": "subject", "ids": [8]},
        "params": {
            "alternatives": [
                [
                    {"weekdays": [2], "periods": [3, 4], "count": 1},
                    {"weekdays": [4], "periods": [6, 7], "count": 1},
                ],
                [
                    {"weekdays": [2], "periods": [6, 7], "count": 1},
                    {"weekdays": [4], "periods": [3, 4], "count": 1},
                ],
            ]
        },
    })
    items = [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=8, teacher_id=7, weekday=2, period=3),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=8, teacher_id=7, weekday=4, period=4),
    ]

    result = evaluate_rule_group(group, items, schedule_available=True)

    assert result.valid is False
    assert result.results[0].status == "fail"


def test_slot_teacher_role_rule_requires_the_class_head_teacher_at_the_selected_slot():
    group = _group({
        "id": "R02",
        "title": "周六第9节安排班主任",
        "code": "slot_teacher_role_required",
        "priority": "hard",
        "target": {"type": "slot", "ids": [609]},
        "params": {"teacher_role": "head_teacher"},
    })
    result = evaluate_rule_group(
        group,
        [
            ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=8, weekday=6, period=9),
            ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=6, period=9),
        ],
        class_head_teacher_ids={10: 7, 11: 7},
    )

    assert result.valid is False
    assert result.results[0].status == "fail"
    assert result.results[0].violation_count == 1


def test_slot_teacher_role_accepts_global_weekdays_and_periods():
    from app.services.scheduling.rules import generation_required_teacher_slots

    group = _group({
        "id": "R02-g",
        "title": "周六晚自习班主任",
        "code": "slot_teacher_role_required",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
        "weekdays": [6],
        "periods": [10],
        "period_scope": "evening",
        "params": {"teacher_role": "head_teacher"},
    })

    assert compile_rule_group(group)[0].status == "ready"
    assert generation_required_teacher_slots(group) == {(6, 10)}


def test_slot_teacher_role_rule_is_unresolved_without_class_head_teacher_mapping():
    group = _group({
        "id": "R02",
        "title": "周六第9节安排班主任",
        "code": "slot_teacher_role_required",
        "priority": "hard",
        "target": {"type": "slot", "ids": [609]},
        "params": {"teacher_role": "head_teacher"},
    })

    result = evaluate_rule_group(
        group,
        [ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=9)],
    )

    assert result.valid is False
    assert result.results[0].status == "unresolved"


def test_class_self_study_day_is_periods_8_and_9_not_empty_evening():
    group = _group(
        {
            "id": "R19-03",
            "title": "10班自习日",
            "code": "class_evening_self_study_day",
            "priority": "hard",
            "target": {"type": "class", "ids": [10]},
            "weekdays": [3, 4, 5],
            "periods": [8, 9],
            "period_scope": "regular",
            "params": {"choose_count": 1},
        },
        {
            "id": "R23",
            "title": "主科尽量靠前",
            "code": "subject_prefer_early_periods",
            "priority": "soft",
            "target": {"type": "subject", "ids": [1]},
        },
    )
    # 周四第8、9节空着=自习；三天晚自习都有教师课，不能当成自习。
    valid = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=8),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=5, period=8),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=10),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=1, teacher_id=7, weekday=4, period=10),
        ScheduleItem(assignment_id=5, class_id=10, subject_id=1, teacher_id=7, weekday=5, period=10),
    ], evening_start_period=10)
    assert valid.valid is True
    assert valid.results[0].status == "pass"
    assert valid.results[0].metrics["self_study_days"] == 1

    # 三天第8节都有主科 → 0 天自习，失败（晚自习空着也不算自习）
    empty_evening = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=8),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=4, period=8),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=5, period=8),
    ], evening_start_period=10)
    assert empty_evening.valid is False

    # 三天第8、9节都空、晚自习都满 → 3 天自习，至少 1 天即通过
    all_study = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=10),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=4, period=10),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=5, period=10),
    ], evening_start_period=10)
    assert all_study.valid is True
    assert generation_evening_free_days(group) == {}
    assert generation_evening_self_study_candidates(group) == {}


def test_teacher_gap_free_detects_interior_gaps_only():
    group = _group({
        "id": "R24",
        "title": "周六教师无空节",
        "code": "teacher_gap_free",
        "priority": "soft",
        "target": {"type": "teacher", "ids": [7, 8]},
        "weekdays": [6],
    })
    # 教师A 周六 1、2、3 节连续；教师B 周六 1、3 节有空节
    result = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=1),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=6, period=2),
        ScheduleItem(assignment_id=3, class_id=12, subject_id=1, teacher_id=7, weekday=6, period=3),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=2, teacher_id=8, weekday=6, period=1),
        ScheduleItem(assignment_id=5, class_id=11, subject_id=2, teacher_id=8, weekday=6, period=3),
    ])

    assert result.results[0].status == "fail"
    # 按周实例：parity=all 的课同时计入单/双周实例，teacher 8 的 {1,3} 在两个实例都有空堂
    assert result.results[0].violation_count == 2
    assert result.results[0].metrics["checked_teacher_days"] == 4


def test_teacher_gap_free_subject_target_expands_to_those_teachers_full_day():
    group = _group({
        "id": "R04-continuity",
        "title": "工作日教师无空节",
        "code": "teacher_gap_free",
        "priority": "hard",
        "target": {"type": "subject", "ids": [12]},
        "weekdays": [1, 2, 3, 4, 5],
    })
    compiled = compile_rule_group(group)[0]
    assert compiled.status == "ready"
    assert generation_gap_free_groups(
        group,
        teachers_by_subject={12: [7], 30: [9]},
    ) == [{"teachers": [7], "weekdays": [1, 2, 3, 4, 5]}]

    # 教师 7 任教学科 12，空节按全天课判断（含其它学科）
    gapped = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=12, teacher_id=7, weekday=1, period=1),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=99, teacher_id=7, weekday=1, period=3),
    ])
    pe_only = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=30, teacher_id=9, weekday=1, period=1),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=30, teacher_id=9, weekday=1, period=3),
    ])
    assert gapped.results[0].status == "fail"
    assert pe_only.results[0].status == "pass"


def test_class_allowed_subject_rules_feed_the_generator():
    group = _group({
        "id": "R18",
        "title": "10班晚间活动课限制",
        "code": "class_allowed_subjects",
        "priority": "hard",
        "target": {"type": "class", "ids": [10]},
        "weekdays": [1, 2],
        "periods": [8, 9],
        "params": {"allowed_subject_ids": [20, 21]},
    })

    assert generation_class_slot_allowed_subjects(group) == {
        10: {(1, 8): {20, 21}, (1, 9): {20, 21}, (2, 8): {20, 21}, (2, 9): {20, 21}},
    }


def test_class_allowed_forbid_all_wins_over_activity_allow_list():
    group = _group(
        {
            "id": "R18-s",
            "title": "第8、9节仅活动课",
            "code": "class_allowed_subjects",
            "priority": "hard",
            "target": {"type": "class", "ids": [10]},
            "weekdays": [1, 4],
            "periods": [8, 9],
            "params": {"allowed_subject_ids": [20, 21, 22], "require_occupied_slots": False},
        },
        {
            "id": "R18-b",
            "title": "周四第8、9节不排课",
            "code": "class_allowed_subjects",
            "priority": "hard",
            "target": {"type": "class", "ids": [10]},
            "weekdays": [4],
            "periods": [8, 9],
            "params": {"allowed_subject_ids": [], "forbid_all": True},
        },
    )

    slots = generation_class_slot_allowed_subjects(group)
    assert slots[10][(1, 8)] == {20, 21, 22}
    assert slots[10][(4, 8)] == set()
    assert slots[10][(4, 9)] == set()


def test_r18b_class10_thursday_late_slots_forbid_every_subject():
    group = _group({
        "id": "R18-b",
        "title": "10班周四第8、9节不排课",
        "code": "class_allowed_subjects",
        "priority": "hard",
        "target": {"type": "class", "ids": [10]},
        "weekdays": [4],
        "periods": [8, 9],
        "params": {"allowed_subject_ids": [], "forbid_all": True},
    })
    empty = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=4, period=1),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=20, teacher_id=8, weekday=1, period=8),
    ])
    activity = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=20, teacher_id=8, weekday=4, period=8),
    ])
    core = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=4, period=9),
    ])

    assert compile_rule_group(group)[0].status == "ready"
    assert generation_class_slot_allowed_subjects(group) == {
        10: {(4, 8): set(), (4, 9): set()},
    }
    assert empty.results[0].status == "pass"
    assert activity.results[0].status == "fail"
    assert core.results[0].status == "fail"


def test_subject_period_preference_rules_feed_the_generator():
    group = _group(
        {
            "id": "R23",
            "title": "主科尽量靠前",
            "code": "subject_prefer_early_periods",
            "priority": "soft",
            "target": {"type": "subject", "ids": [1, 2, 3]},
        },
        {
            "id": "R24",
            "title": "活动课补空节",
            "code": "subject_gap_fill_late_periods",
            "priority": "soft",
            "target": {"type": "subject", "ids": [20, 21]},
            "params": {"late_from_period": 8},
        },
    )
    assert generation_early_subject_ids(group) == {1, 2, 3}
    assert generation_gap_fill_late_subjects(group) == ({20, 21}, 8)
    summary = evaluate_rule_group(
        group,
        [
            ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=2),
            ScheduleItem(assignment_id=2, class_id=10, subject_id=20, teacher_id=8, weekday=1, period=8),
        ],
        evening_start_period=10,
    )
    assert summary.valid is True
    by_id = {item.rule_id: item for item in summary.results}
    assert by_id["R23"].status == "pass"
    assert by_id["R24"].status == "pass"


def test_prefer_early_counts_lessons_outside_selected_periods():
    group = _group({
        "id": "R23",
        "title": "主科尽量靠前",
        "code": "subject_prefer_early_periods",
        "priority": "soft",
        "target": {"type": "subject", "ids": [1]},
        "periods": [1, 2, 3, 4, 5],
        "params": {"max_outside": 1},
    })
    prefs = generation_early_subject_prefs(group)
    assert prefs[0]["max_outside"] == 1
    assert prefs[0]["periods"] == [1, 2, 3, 4, 5]
    ok = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=2),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=8),
    ], evening_start_period=10)
    over = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=8),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=9),
    ], evening_start_period=10)
    assert ok.results[0].status == "pass"
    assert over.results[0].status == "fail"
    assert over.results[0].violation_count == 1


def test_gap_fill_does_not_count_hard_forbidden_late_slots_as_vacancies():
    group = _group(
        {
            "id": "R24",
            "title": "活动课补空节",
            "code": "subject_gap_fill_late_periods",
            "priority": "soft",
            "target": {"type": "subject", "ids": [20]},
            "params": {"late_from_period": 8},
        },
        {
            "id": "R18",
            "title": "周一第8、9节不排课",
            "code": "class_allowed_subjects",
            "priority": "hard",
            "target": {"type": "class", "ids": [10]},
            "weekdays": [1],
            "periods": [8, 9],
            "params": {"allowed_subject_ids": [], "forbid_all": True},
        },
    )
    summary = evaluate_rule_group(
        group,
        [
            ScheduleItem(assignment_id=1, class_id=10, subject_id=20, teacher_id=8, weekday=1, period=3),
            ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=1),
        ],
        evening_start_period=10,
    )
    by_id = {item.rule_id: item for item in summary.results}
    assert by_id["R24"].status == "pass"


def test_r17_period_five_caps_each_teacher_at_two_lessons():
    group = _group({
        "id": "R17-02",
        "title": "第5节教师每周最多2节",
        "code": "slot_teacher_balance",
        "priority": "hard",
        "target": {"type": "global", "ids": []},
        "weekdays": [1, 2, 3, 4, 5, 6],
        "periods": [5],
        "params": {"max_per_teacher": 2},
    })
    compiled = compile_rule_group(group)
    ok = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=index, class_id=10 + index, subject_id=1, teacher_id=7, weekday=index, period=5)
        for index in range(1, 3)
    ])
    over = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=index, class_id=10 + index, subject_id=1, teacher_id=7, weekday=index, period=5)
        for index in range(1, 4)
    ])

    assert compiled[0].status == "ready"
    assert generation_slot_teacher_balance_scope(group) == ([1, 2, 3, 4, 5, 6], [5], 2)
    assert ok.results[0].status == "pass"
    assert over.results[0].status == "fail"
    assert over.results[0].violation_count == 1


def test_cpsat_caps_period_five_lessons_per_teacher():
    cap = {"weekdays": [1, 2, 3, 4, 5], "periods": [5], "cap": 2}
    forbidden = {(day, period) for day in range(1, 6) for period in range(1, 6) if period != 5}
    over = solve_daytime_cpsat(
        [
            {"id": index, "class_id": index, "subject_id": 1, "teacher_id": 7, "weekly_periods": 1}
            for index in range(1, 4)
        ],
        days=5,
        periods_per_day=5,
        forbidden_slots=forbidden,
        slot_teacher_cap=cap,
        max_time_seconds=5,
    )
    ok = solve_daytime_cpsat(
        [
            {"id": index, "class_id": index, "subject_id": 1, "teacher_id": 7, "weekly_periods": 1}
            for index in range(1, 3)
        ],
        days=5,
        periods_per_day=5,
        forbidden_slots=forbidden,
        slot_teacher_cap=cap,
        max_time_seconds=5,
    )
    assert over.status == "INFEASIBLE"
    assert ok.status in {"OPTIMAL", "FEASIBLE"}
    assert sum(item.period == 5 for item in ok.items) == 2


def test_cpsat_class_slot_allow_list_can_leave_the_slot_empty():
    result = solve_daytime_cpsat(
        [{"id": 1, "class_id": 10, "subject_id": 1, "teacher_id": 7, "weekly_periods": 1}],
        days=1,
        periods_per_day=8,
        class_slot_allowed_subjects={10: {(1, 8): {20, 21, 22}}},
        max_time_seconds=2,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.items
    assert all(not (item.weekday == 1 and item.period == 8) for item in result.items)


def test_cpsat_forbid_all_keeps_thursday_late_slots_empty():
    result = solve_daytime_cpsat(
        [{"id": 1, "class_id": 10, "subject_id": 20, "teacher_id": 8, "weekly_periods": 1}],
        days=4,
        periods_per_day=9,
        class_slot_allowed_subjects={10: {(4, 8): set(), (4, 9): set()}},
        max_time_seconds=2,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.items
    assert all(not (item.weekday == 4 and item.period in {8, 9}) for item in result.items)


def test_evening_parity_pair_rule_checks_same_slot_across_weeks():
    group = _group({
        "id": "R22",
        "title": "物理历史晚课单双周配对",
        "code": "subject_evening_parity_pair",
        "priority": "hard",
        "target": {"type": "subject", "ids": [26, 32]},
        "period_scope": "evening",
    })
    aligned = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=26, teacher_id=7, weekday=3, period=9, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=32, teacher_id=8, weekday=3, period=9, week_parity="even"),
    ])
    misaligned = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=26, teacher_id=7, weekday=3, period=9, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=32, teacher_id=8, weekday=5, period=9, week_parity="even"),
    ])

    assert aligned.results[0].status == "pass"
    assert misaligned.results[0].status == "fail"
    assert misaligned.results[0].violation_count == 1

    # 反方向（历史单周、物理双周）同样合规：客户未规定谁单谁双
    reversed_pairs = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=32, teacher_id=8, weekday=3, period=9, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=26, teacher_id=7, weekday=3, period=9, week_parity="even"),
    ])
    assert reversed_pairs.results[0].status == "pass"


def test_evening_parity_pair_extraction_feeds_the_builder():
    group = _group({
        "id": "R22",
        "title": "物理历史晚课单双周配对",
        "code": "subject_evening_parity_pair",
        "priority": "hard",
        "target": {"type": "subject", "ids": [26, 32]},
        "period_scope": "evening",
    })

    assert generation_evening_parity_pairs(group) == [(26, 32)]


def test_daytime_parity_pair_same_slot_and_ignores_other_days():
    group = _group({
        "id": "R-sat-pair",
        "title": "周六单周生化双周历地",
        "code": "subject_daytime_parity_pair",
        "priority": "hard",
        "target": {"type": "subject", "ids": [30, 33, 32, 25]},
        "weekdays": [6],
        "periods": [1, 2, 3],
        "period_scope": "regular",
        "params": {"odd_subject_ids": [30, 33], "even_subject_ids": [32, 25]},
    })
    aligned = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=30, teacher_id=7, weekday=6, period=2, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=33, teacher_id=9, weekday=6, period=1, week_parity="odd"),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=32, teacher_id=8, weekday=6, period=3, week_parity="even"),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=25, teacher_id=6, weekday=6, period=1, week_parity="even"),
    ])
    # 不同节次也合规：老师不要求同格对课
    different_slots = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=30, teacher_id=7, weekday=6, period=1, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=33, teacher_id=9, weekday=6, period=2, week_parity="odd"),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=32, teacher_id=8, weekday=6, period=3, week_parity="even"),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=25, teacher_id=6, weekday=6, period=2, week_parity="even"),
    ])
    reversed_leg = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=32, teacher_id=8, weekday=6, period=1, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=30, teacher_id=7, weekday=6, period=1, week_parity="even"),
    ])
    other_day = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=30, teacher_id=7, weekday=1, period=2, week_parity="odd"),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=32, teacher_id=8, weekday=1, period=3, week_parity="even"),
    ])
    assert aligned.results[0].status == "pass"
    assert different_slots.results[0].status == "pass"
    assert reversed_leg.results[0].status == "fail"
    assert other_day.results[0].status == "pass"
    assert generation_daytime_parity_pairs(group) == [{
        "odd_subjects": [30, 33],
        "even_subjects": [32, 25],
        "subjects": (),
        "weekdays": [6],
        "periods": [1, 2, 3],
    }]


def test_cpsat_daytime_parity_pair_forces_same_saturday_slot():
    pair = {
        "odd_subjects": [30, 33],
        "even_subjects": [32, 25],
        "weekdays": [6],
        "periods": [1, 2],
    }
    result = solve_daytime_cpsat(
        [
            {
                "id": 1, "class_id": 10, "subject_id": 30, "teacher_id": 7,
                "weekly_periods": 0.5, "weekday_periods": 0, "saturday_periods": 0.5,
            },
            {
                "id": 2, "class_id": 10, "subject_id": 33, "teacher_id": 9,
                "weekly_periods": 0.5, "weekday_periods": 0, "saturday_periods": 0.5,
            },
            {
                "id": 3, "class_id": 10, "subject_id": 32, "teacher_id": 8,
                "weekly_periods": 0.5, "weekday_periods": 0, "saturday_periods": 0.5,
            },
            {
                "id": 4, "class_id": 10, "subject_id": 25, "teacher_id": 6,
                "weekly_periods": 0.5, "weekday_periods": 0, "saturday_periods": 0.5,
            },
        ],
        days=6,
        periods_per_day=2,
        daytime_parity_pairs=[pair],
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    odd_items = [item for item in result.items if item.week_parity == WeekParity.odd]
    even_items = [item for item in result.items if item.week_parity == WeekParity.even]
    assert {item.subject_id for item in odd_items} == {30, 33}
    assert {item.subject_id for item in even_items} == {32, 25}
    assert all(item.weekday == 6 for item in odd_items + even_items)


def test_class_evening_teacher_pins_feed_required_slots():
    group = _group({
        "id": "R19-01",
        "title": "张卓10班周一晚课",
        "code": "teacher_preferred_weekdays",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [695]},
        "weekdays": [1],
        "periods": [10],
        "period_scope": "evening",
        "params": {"class_id": 636},
    })
    assert generation_class_slot_required_teachers(group) == {(1, 10): {636: 695}}


def test_class_evening_pin_eval_ignores_teacher_other_class_evenings():
    """R19-01/R19-02 是班别钉位：10班周一有张卓即过，不因7班周二而判 R19-01 失败。"""
    group = _group(
        {
            "id": "R19-01",
            "title": "张卓10班周一晚课",
            "code": "teacher_preferred_weekdays",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [695]},
            "weekdays": [1],
            "periods": [10],
            "period_scope": "evening",
            "params": {"class_id": 636},
        },
        {
            "id": "R19-02",
            "title": "张卓7班周二晚课",
            "code": "teacher_preferred_weekdays",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [695]},
            "weekdays": [2],
            "periods": [10],
            "period_scope": "evening",
            "params": {"class_id": 633},
        },
    )
    items = [
        ScheduleItem(assignment_id=1, class_id=636, subject_id=1, teacher_id=695, weekday=1, period=10),
        ScheduleItem(assignment_id=2, class_id=633, subject_id=1, teacher_id=695, weekday=2, period=10),
    ]
    result = evaluate_rule_group(group, items, evening_start_period=10)
    assert all(row.status == "pass" for row in result.results)
    missing = evaluate_rule_group(
        group,
        [ScheduleItem(assignment_id=2, class_id=633, subject_id=1, teacher_id=695, weekday=2, period=10)],
        evening_start_period=10,
    )
    by_id = {row.rule_id: row for row in missing.results}
    assert by_id["R19-01"].status == "fail"
    assert by_id["R19-02"].status == "pass"


def test_evening_period_one_is_remapped_to_period_ten():
    """「第10节」曾被存成 periods=[1]，晚课生成/禁排必须落到第10节。"""
    pin = _group({
        "id": "R19-01",
        "title": "张卓10班周一晚课",
        "code": "teacher_preferred_weekdays",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [695]},
        "weekdays": [1],
        "periods": [1],
        "period_scope": "evening",
        "params": {"class_id": 636},
    })
    ban = _group({
        "id": "R06",
        "title": "黄淑梅晚课仅周一周二",
        "code": "teacher_forbidden_slots",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [679]},
        "weekdays": [3, 4, 5, 6],
        "periods": [1],
        "period_scope": "evening",
    })
    assert generation_class_slot_required_teachers(pin) == {(1, 10): {636: 695}}
    assert generation_teacher_forbidden_slots(ban)[679] == {(3, 10), (4, 10), (5, 10), (6, 10)}


def test_r06_requires_monday_and_tuesday_evening_for_two_classes():
    group = _group({
        "id": "R06",
        "title": "黄淑梅晚课仅周一周二",
        "code": "teacher_forbidden_slots",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [679]},
        "weekdays": [3, 4, 5, 6],
        "periods": [10],
        "period_scope": "evening",
        "params": {"require_weekdays": [1, 2]},
    })
    swapped = [
        ScheduleItem(assignment_id=1, class_id=627, subject_id=12, teacher_id=679, weekday=1, period=10),
        ScheduleItem(assignment_id=2, class_id=628, subject_id=12, teacher_id=679, weekday=2, period=10),
    ]
    only_tue = swapped[1:]
    same_class = [
        ScheduleItem(assignment_id=1, class_id=627, subject_id=12, teacher_id=679, weekday=1, period=10),
        ScheduleItem(assignment_id=2, class_id=627, subject_id=12, teacher_id=679, weekday=2, period=10),
    ]
    ok = evaluate_rule_group(group, swapped, evening_start_period=10)
    missing = evaluate_rule_group(group, only_tue, evening_start_period=10)
    dup = evaluate_rule_group(group, same_class, evening_start_period=10)
    assert ok.results[0].status == "pass"
    assert missing.results[0].status == "fail"
    assert dup.results[0].status == "fail"
    assert generation_teacher_required_evening_weekdays(group) == {679: {1, 2}}


def test_required_class_subject_slots_fail_when_an_allowed_slot_is_empty():
    group = _group({
        "id": "R18",
        "title": "10班指定课位必须排音美心",
        "code": "class_allowed_subjects",
        "priority": "hard",
        "target": {"type": "class", "ids": [10]},
        "weekdays": [1, 2],
        "periods": [8],
        "params": {"allowed_subject_ids": [20, 21], "require_occupied_slots": True},
    })

    missing = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=20, teacher_id=7, weekday=1, period=8),
    ])
    complete = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=20, teacher_id=7, weekday=1, period=8),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=21, teacher_id=8, weekday=2, period=8),
    ])

    assert missing.results[0].status == "fail"
    assert missing.results[0].violation_count == 1
    assert complete.results[0].status == "pass"
    assert generation_class_required_subject_slots(group) == {
        10: {(1, 8): {20, 21}, (2, 8): {20, 21}},
    }


def test_teacher_evening_daytime_link_is_a_blocking_hard_rule():
    group = _group({
        "id": "R10-b",
        "title": "黄丽娟晚课联动",
        "code": "teacher_evening_daytime_link",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7]},
        "period_scope": "any",
        "params": {
            "evening_start_period": 9,
            "required_daytime_period": 7,
        },
    })
    missing_seventh = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=4),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=2, period=5),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=9),
    ], evening_start_period=9)
    # 第7节在晚课日；另外两节在别的工作日的 3/4/5，不再要求与晚课同一天。
    valid = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=4),
        ScheduleItem(assignment_id=2, class_id=11, subject_id=1, teacher_id=7, weekday=3, period=5),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=7),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=9),
    ], evening_start_period=9)

    assert missing_seventh.results[0].status == "fail"
    assert blocking_rule_results(missing_seventh)[0].rule_id == "R10-b"
    assert valid.results[0].status == "pass"


def test_teacher_period_minimum_counts_across_weekdays():
    group = _group({
        "id": "R10-c",
        "title": "黄丽娟第3/4/5节下限",
        "code": "teacher_period_minimum",
        "priority": "hard",
        "target": {"type": "teacher", "ids": [7]},
        "periods": [3, 4, 5],
        "period_scope": "regular",
        "params": {"minimum_lessons": 2},
    })
    too_few = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=7),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=4),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=9),
    ], evening_start_period=9)
    enough = evaluate_rule_group(group, [
        ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=1, period=4),
        ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=3, period=5),
        ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=7),
        ScheduleItem(assignment_id=4, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=9),
    ], evening_start_period=9)
    sat_only = evaluate_rule_group(
        _group({
            "id": "R10-c",
            "title": "黄丽娟第3/4/5节下限",
            "code": "teacher_period_minimum",
            "priority": "hard",
            "target": {"type": "teacher", "ids": [7]},
            "weekdays": [1, 2, 3, 4, 5],
            "periods": [3, 4, 5],
            "period_scope": "regular",
            "params": {"minimum_lessons": 2},
        }),
        [
            ScheduleItem(assignment_id=1, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=3),
            ScheduleItem(assignment_id=2, class_id=10, subject_id=1, teacher_id=7, weekday=6, period=4),
            ScheduleItem(assignment_id=3, class_id=10, subject_id=1, teacher_id=7, weekday=2, period=7),
        ],
        evening_start_period=10,
    )

    assert too_few.results[0].status == "fail"
    assert blocking_rule_results(too_few)[0].rule_id == "R10-c"
    assert enough.results[0].status == "pass"
    assert sat_only.results[0].status == "fail"


def test_cpsat_requires_an_allowed_subject_in_every_required_class_slot():
    result = solve_daytime_cpsat(
        [{"id": 1, "class_id": 10, "subject_id": 20, "teacher_id": 7, "weekly_periods": 2}],
        days=2,
        periods_per_day=8,
        class_slot_allowed_subjects={10: {(1, 8): {20}, (2, 8): {20}}},
        class_required_subject_slots={10: {(1, 8): {20}, (2, 8): {20}}},
        max_time_seconds=2,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert {(item.weekday, item.period, item.subject_id) for item in result.items} == {
        (1, 8, 20), (2, 8, 20),
    }


def test_cpsat_subject_six_weekday_periods_use_four_plus_two_distribution():
    result = solve_daytime_cpsat(
        [{
            "id": 1,
            "class_id": 10,
            "subject_id": 29,
            "teacher_id": 7,
            "weekday_periods": 6,
            "saturday_periods": 0,
            "weekly_periods": 6,
        }],
        days=5,
        periods_per_day=8,
        subject_daily_spread=True,
        max_time_seconds=2,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    counts = {
        weekday: sum(item.weekday == weekday for item in result.items)
        for weekday in range(1, 6)
    }
    assert sorted(counts.values()) == [1, 1, 1, 1, 2]


def test_cpsat_subject_five_weekday_periods_use_one_per_weekday():
    result = solve_daytime_cpsat(
        [{
            "id": 1,
            "class_id": 10,
            "subject_id": 12,
            "teacher_id": 7,
            "weekday_periods": 5,
            "saturday_periods": 0,
            "weekly_periods": 5,
        }],
        days=5,
        periods_per_day=8,
        subject_daily_spread=True,
        max_time_seconds=2,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    counts = {
        weekday: sum(item.weekday == weekday for item in result.items)
        for weekday in range(1, 6)
    }
    assert counts == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}


def test_cpsat_uses_activity_lessons_only_after_core_subjects_take_early_periods():
    result = solve_daytime_cpsat(
        [
            {"id": 1, "class_id": 10, "subject_id": 1, "teacher_id": 7, "weekly_periods": 1},
            {"id": 2, "class_id": 10, "subject_id": 20, "teacher_id": 8, "weekly_periods": 1},
        ],
        days=1,
        periods_per_day=3,
        early_subject_ids={1},
        gap_fill_subject_ids={20},
        gap_fill_late_from_period=3,
        max_time_seconds=5,
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    by_subject = {item.subject_id: item.period for item in result.items}
    assert by_subject[1] == 1
    assert by_subject[20] == 3


def test_cpsat_at_most_one_activity_lesson_per_class_day():
    """音美心同一班级同一天最多一节，不能叠两节活动课。"""
    too_tight = solve_daytime_cpsat(
        [
            {"id": 1, "class_id": 1, "subject_id": 20, "teacher_id": 8, "weekly_periods": 1},
            {"id": 2, "class_id": 1, "subject_id": 21, "teacher_id": 9, "weekly_periods": 1},
            {"id": 3, "class_id": 1, "subject_id": 22, "teacher_id": 10, "weekly_periods": 1},
        ],
        days=2,
        periods_per_day=9,
        subject_forbidden_slots={
            sid: {(day, period) for day in (1, 2) for period in range(1, 8)}
            for sid in (20, 21, 22)
        },
        gap_fill_subject_ids={20, 21, 22},
        gap_fill_late_from_period=8,
        max_time_seconds=3,
    )
    assert too_tight.status == "INFEASIBLE"

    ok = solve_daytime_cpsat(
        [
            {"id": 1, "class_id": 1, "subject_id": 20, "teacher_id": 8, "weekly_periods": 1},
            {"id": 2, "class_id": 1, "subject_id": 21, "teacher_id": 9, "weekly_periods": 1},
            {"id": 3, "class_id": 1, "subject_id": 22, "teacher_id": 10, "weekly_periods": 1},
        ],
        days=3,
        periods_per_day=9,
        subject_forbidden_slots={
            sid: {(day, period) for day in (1, 2, 3) for period in range(1, 8)}
            for sid in (20, 21, 22)
        },
        gap_fill_subject_ids={20, 21, 22},
        gap_fill_late_from_period=8,
        max_time_seconds=3,
    )
    assert ok.status in {"OPTIMAL", "FEASIBLE"}
    by_day: dict[int, int] = {}
    for item in ok.items:
        by_day[item.weekday] = by_day.get(item.weekday, 0) + 1
    assert all(count <= 1 for count in by_day.values())


def test_parse_legacy_rule_group_as_single_catalog_entry():
    groups, active_id = parse_stored_rule_groups(_group().model_dump(mode="json"))
    assert len(groups) == 1
    assert groups[0].id == "grade-1-rules"
    assert groups[0].grade_id is None
    assert active_id is None


def test_dump_catalog_keeps_legacy_document_fields():
    g1 = _group()
    g1.grade_id = 12
    g2 = RuleGroupDocument(
        id="grade-2-rules",
        name="高二组排课规则",
        academic_year="2026-2027",
        term="1",
        grade_id=13,
        rules=[],
    )
    dumped = dump_stored_rule_groups([g1, g2], "grade-1-rules")
    assert dumped["id"] == "grade-1-rules"
    assert dumped["grade_id"] == 12
    assert dumped["catalog_version"] == 2
    assert len(dumped["groups"]) == 2
    parsed, active_id = parse_stored_rule_groups(dumped)
    assert active_id == "grade-1-rules"
    assert pick_rule_group(parsed, grade_id=13).id == "grade-2-rules"
    assert pick_rule_group(parsed, group_id="grade-1-rules").grade_id == 12
    legacy = RuleGroupDocument.model_validate(dumped)
    assert legacy.id == "grade-1-rules"
    assert legacy.grade_id == 12

