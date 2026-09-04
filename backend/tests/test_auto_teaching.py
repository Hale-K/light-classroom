from app.services.academic.auto_teaching import (
    TeacherScopeRule,
    apply_subject_periods,
    assignments_outside_rebuild_scope,
    build_auto_assignments,
    target_class_ids,
)


def test_auto_teaching_uses_classes_in_current_term_only():
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 2, "subject_id": 20, "class_id": 101, "weekly_periods": 4},
    ]

    assert target_class_ids(assignments, [100, 101, 200, 201]) == [100, 101]


def test_configured_subject_periods_apply_to_existing_relations():
    assignments = [{"teacher_id": 1, "subject_id": 11, "class_id": 100, "weekly_periods": 1}]

    planned = apply_subject_periods(assignments, {11: 2})

    assert planned[0]["weekly_periods"] == 2
    assert assignments[0]["weekly_periods"] == 1


def test_template_rebuild_removes_old_relations_only_inside_selected_scope():
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 5},
        {"teacher_id": 2, "subject_id": 20, "class_id": 100, "weekly_periods": 5},
        {"teacher_id": 3, "subject_id": 10, "class_id": 200, "weekly_periods": 5},
    ]

    remaining = assignments_outside_rebuild_scope(assignments, [100], [10, 20])

    assert remaining == [
        {"teacher_id": 3, "subject_id": 10, "class_id": 200, "weekly_periods": 5},
    ]


def test_auto_teaching_reciprocal_fill_and_scope_rules():
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 2, "subject_id": 20, "class_id": 101, "weekly_periods": 4},
    ]

    created, skipped = build_auto_assignments(
        assignments,
        [100, 101],
        [TeacherScopeRule(teacher_id=1, class_id=101, mode="allow"),
         TeacherScopeRule(teacher_id=2, class_id=100, mode="allow")],
    )

    assert {(item["teacher_id"], item["subject_id"], item["class_id"]) for item in created} == {
        (1, 10, 101), (2, 20, 100),
    }
    assert skipped == []


def test_deny_rule_wins_and_reports_unmatched():
    assignments = [{"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4}]
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101],
        [TeacherScopeRule(teacher_id=1, class_id=101, mode="deny")],
    )

    assert created == []
    assert skipped == [{"class_id": 101, "subject_id": 10, "reason": "没有符合授课范围或课时上限的教师"}]


def test_scope_rule_pins_teacher_to_subject():
    """subject 限定的固定任教：该班该科必须由该教师担任，且不限制教师承担其他班级。"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 1, "subject_id": 20, "class_id": 100, "weekly_periods": 4},
    ]
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101],
        [TeacherScopeRule(teacher_id=1, class_id=101, subject_id=10, mode="allow")],
    )
    created_keys = {(item["teacher_id"], item["subject_id"], item["class_id"]) for item in created}
    # 101 班的 10 学科按固定规则由教师 1 担任
    assert (1, 10, 101) in created_keys
    # 教师 1 未被限制：101 班的 20 学科(唯一有资质的教师)也由其承担
    assert (1, 20, 101) in created_keys
    assert skipped == []


def test_pin_rule_does_not_restrict_other_classes():
    """固定任教(allow)只保证目标班,不会把教师锁死在白名单里(回归:地理教师被限1个班)。"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
    ]
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101, 102],
        [TeacherScopeRule(teacher_id=1, class_id=100, mode="allow")],
        max_weekly_periods=30,
    )
    created_keys = {(item["teacher_id"], item["subject_id"], item["class_id"]) for item in created}
    # 教师 1 固定带 100(已满足),还能继续带 101、102
    assert (1, 10, 101) in created_keys
    assert (1, 10, 102) in created_keys
    assert skipped == []


def test_pin_rule_unsatisfiable_reports_reason():
    """固定任教无法满足时给出明确原因,且不阻断其他缺口的正常匹配。"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
    ]
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101],
        [TeacherScopeRule(teacher_id=1, class_id=101, subject_id=20, mode="allow")],
    )
    # 教师 1 无 20 学科资质：固定规则无法满足 → 报告原因
    assert any("固定任教" in item["reason"] for item in skipped), skipped
    # 101 班 10 学科仍正常匹配给教师 1
    assert (1, 10, 101) in {(item["teacher_id"], item["subject_id"], item["class_id"]) for item in created}


def test_auto_teaching_covers_classes_without_existing_relations():
    """全新年级（无任何已有任教关系）也能按学科范围从零自动生成。"""
    # 没有任何任教关系：rows 为空
    assignments = []
    # 但明确指定了要生成的学科范围（学科字典兜底）
    created, skipped = build_auto_assignments(
        assignments,
        [200, 201],
        [],
        weekly_periods=4,
        max_weekly_periods=20,
        subject_ids=[10, 20],
    )
    # 没有教师具备学科资格 → 全部无法匹配（合理：必须先有教师/学科基础数据）
    assert created == []
    assert len(skipped) == 4  # 2 班 × 2 科


def test_auto_teaching_all_classes_when_subject_ids_given():
    """已有教师学科资格时，未指定 class_ids 也能覆盖全部班级（含无数据班级）。"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 2, "subject_id": 20, "class_id": 100, "weekly_periods": 4},
    ]
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101, 200],
        [],
        weekly_periods=4,
        max_weekly_periods=20,
        subject_ids=[10, 20],
    )
    created_keys = {(item["teacher_id"], item["subject_id"], item["class_id"]) for item in created}
    # 教师1带学科10 覆盖 101 和 200；教师2带学科20 覆盖 101 和 200
    assert (1, 10, 101) in created_keys
    assert (1, 10, 200) in created_keys
    assert (2, 20, 101) in created_keys
    assert (2, 20, 200) in created_keys
    assert skipped == []


def test_time_structure_caps_same_subject_and_class_weekly():
    """时间结构：同科每日上限×教学日 限制单科周课时；班级周容量限制总课时"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 2, "subject_id": 20, "class_id": 101, "weekly_periods": 4},
    ]
    # 同科每日最多 2 节 × 每周 5 天 = 同科每周上限 10；班级每日 6 节 × 5 天 = 周容量 30
    created, skipped = build_auto_assignments(
        assignments,
        [100, 101],
        [],
        weekly_periods=4,
        days=5,
        periods_per_day=7,
        max_same_subject_per_day=2,
        max_class_lessons_per_day=6,
        max_teacher_lessons_per_day=6,
    )
    # 教师 1 教 10 学科给 101，教师 2 教 20 学科给 100
    assert len(created) == 2, created
    for row in created:
        assert row["weekly_periods"] <= 10  # 同科每周上限
    assert skipped == []


def test_time_structure_reports_class_capacity_skip():
    """班级周容量不足时跳过并给出原因"""
    assignments = [
        {"teacher_id": 1, "subject_id": 10, "class_id": 100, "weekly_periods": 4},
        {"teacher_id": 2, "subject_id": 20, "class_id": 101, "weekly_periods": 4},
        {"teacher_id": 1, "subject_id": 10, "class_id": 102, "weekly_periods": 4},
    ]
    # 班级 102 已有 4 节（10 学科），周容量 10（每日 2 × 5 天）；缺 20 学科，教师 2 可教但班级容量放不下 4 节？
    # 4 + 4 = 8 <= 10，能放下；把容量压到每日 1 节（周容量 5）→ 放不下
    created, skipped = build_auto_assignments(
        assignments,
        [102],
        [],
        weekly_periods=4,
        days=5,
        periods_per_day=4,
        max_same_subject_per_day=2,
        max_class_lessons_per_day=1,
        max_teacher_lessons_per_day=2,
    )
    assert created == [], created
    assert any("班级周课时已达上限" in item["reason"] for item in skipped), skipped


def test_head_teachers_and_subject_teachers_have_no_class_count_limit():
    """班主任和任课教师的班级数量不设固定上限，课时上限仍然生效。"""
    class_ids = list(range(1, 39))
    head_teacher_ids = list(range(101, 114))
    other_teacher_ids = list(range(201, 205))
    rules = [
        TeacherScopeRule(teacher_id=teacher_id, class_id=class_id, subject_id=10, mode="allow")
        for teacher_id, class_id in zip(head_teacher_ids, class_ids)
    ]

    created, skipped = build_auto_assignments(
        [],
        class_ids,
        rules,
        weekly_periods=5,
        max_weekly_periods=20,
        subject_ids=[10],
        subject_weekly_periods={10: 5},
        teacher_subject_fallback={teacher_id: [10] for teacher_id in [*head_teacher_ids, *other_teacher_ids]},
    )

    class_counts = {
        teacher_id: len({row["class_id"] for row in created if row["teacher_id"] == teacher_id})
        for teacher_id in [*head_teacher_ids, *other_teacher_ids]
    }
    assert skipped == []
    assert len(created) == 38
    assert max(class_counts.values()) <= 4  # 20 节周上限 ÷ 每班 5 节


def test_auto_teaching_does_not_limit_classes_per_teacher():
    """教师可以跨多个班任教，自动匹配只受课时和授课资格约束。"""
    assignments = [{"teacher_id": 1, "subject_id": 10, "class_id": 1, "weekly_periods": 5}]

    created, skipped = build_auto_assignments(
        assignments,
        [1, 2, 3, 4],
        [],
        weekly_periods=5,
        max_weekly_periods=30,
        teacher_subject_fallback={1: [10]},
        subject_ids=[10],
    )

    assert {item["class_id"] for item in created} == {2, 3, 4}
    assert skipped == []


def test_activity_relation_without_teacher_is_ignored_by_auto_teaching():
    """活动关系没有任课教师，不应参与自动任教匹配或触发类型转换错误。"""
    created, skipped = build_auto_assignments(
        [{"teacher_id": None, "subject_id": 99, "class_id": 1, "weekly_periods": 1}],
        [1],
        [],
        subject_ids=[10],
        teacher_subject_fallback={1: [10]},
    )

    assert created == [{
        "teacher_id": 1,
        "subject_id": 10,
        "class_id": 1,
        "weekly_periods": 3,
        "student_count": None,
        "suggested_weekly_periods": 3,
    }]
    assert skipped == []


def test_unassigned_teacher_cannot_receive_a_class():
    """学科组资质不等于年级任职资格。"""
    created, skipped = build_auto_assignments(
        [], [1], [], subject_ids=[10],
        teacher_subject_fallback={101: [10], 102: [10]},
        eligible_teacher_ids=[101],
        weekly_periods=5,
        max_weekly_periods=30,
    )

    assert len(created) == 1
    assert created[0]["teacher_id"] == 101
    assert skipped == []


def test_stale_assignment_from_unassigned_teacher_is_rebuilt():
    """旧任教关系不能阻止当前年级重新分配给合资格教师。"""
    created, skipped = build_auto_assignments(
        [{"teacher_id": 102, "subject_id": 10, "class_id": 1, "weekly_periods": 5}],
        [1], [], subject_ids=[10],
        teacher_subject_fallback={101: [10], 102: [10]},
        eligible_teacher_ids=[101],
        weekly_periods=5,
        max_weekly_periods=30,
    )

    assert len(created) == 1
    assert created[0]["teacher_id"] == 101
    assert skipped == []
