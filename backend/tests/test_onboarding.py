"""新手引导九步判定：完成阈值与详情文案。"""
from app.api.v1.onboarding import evaluate_steps


def _steps(**overrides):
    kwargs = dict(
        year="2026-2027", term="1",
        campus_count=2, building_count=4, room_count=60,
        allocation_rule_count=3, allocated_room_count=30,
        resource_assigned_class_count=10,
        grid_configured=True, grid_line="5 天 × 7 节，含晚自习",
        class_total=10, hour_classes=10,
        teacher_count=14, asg_class_count=10,
        rule_group_count=2, enabled_rules=43,
        version_count=1,
    )
    kwargs.update(overrides)
    return evaluate_steps(**kwargs)


def test_ready_school_has_all_nine_done():
    steps = _steps()
    assert len(steps) == 9
    assert all(s["done"] for s in steps)
    assert steps[-1]["detail"] == "已有 1 个课表版本"


def test_new_school_first_steps_incomplete_with_guidance():
    steps = _steps(year=None, campus_count=0, building_count=0, room_count=0,
                   allocation_rule_count=0, allocated_room_count=0, resource_assigned_class_count=0,
                   grid_configured=False, class_total=0, teacher_count=0,
                   rule_group_count=0, enabled_rules=0, version_count=0)
    assert not any(s["done"] for s in steps)
    by_key = {step["key"]: step for step in steps}
    assert "还没有设置当前学年学期" in by_key["year"]["detail"]
    assert "先创建校区" in by_key["space"]["detail"]
    assert "先设置当前学年学期" in by_key["allocation"]["detail"]
    assert "先设置当前学年学期" in by_key["class_planning"]["detail"]
    assert "先设置当前学年学期" in by_key["hours"]["detail"]
    assert "还没有教师和班的对应关系" in by_key["assignments"]["detail"]


def test_space_step_requires_campus_building_and_room():
    campus_only = next(s for s in _steps(campus_count=1, building_count=0, room_count=0) if s["key"] == "space")
    assert not campus_only["done"]
    assert "还没有楼宇" in campus_only["detail"]

    no_room = next(s for s in _steps(campus_count=1, building_count=2, room_count=0) if s["key"] == "space")
    assert not no_room["done"]
    assert "还没有场室" in no_room["detail"]

    complete = next(s for s in _steps(campus_count=1, building_count=2, room_count=12) if s["key"] == "space")
    assert complete["done"]
    assert complete["detail"] == "已有 1 个校区、2 栋楼宇、12 间场室"


def test_allocation_and_class_planning_are_independent_required_steps():
    allocation = next(s for s in _steps(allocation_rule_count=0, allocated_room_count=0) if s["key"] == "allocation")
    assert not allocation["done"]
    assert allocation["path"].endswith("tab=allocation")

    partial = next(s for s in _steps(resource_assigned_class_count=7) if s["key"] == "class_planning")
    assert not partial["done"]
    assert partial["detail"] == "7/10 个行政班已绑定当前学期分配的教室"
    assert partial["path"].endswith("tab=class-planning")

    complete = next(s for s in _steps(resource_assigned_class_count=10) if s["key"] == "class_planning")
    assert complete["done"]


def test_class_planning_requires_classes_after_resources_are_allocated():
    planning = next(s for s in _steps(class_total=0, resource_assigned_class_count=0) if s["key"] == "class_planning")
    assert not planning["done"]
    assert "尚未据此生成行政班" in planning["detail"]

    hours = next(s for s in _steps(class_total=0, hour_classes=0) if s["key"] == "hours")
    assert "班级划分" in hours["detail"]


def test_hours_step_requires_every_class_filled():
    steps = _steps(hour_classes=9)
    hours = next(s for s in steps if s["key"] == "hours")
    assert not hours["done"]
    assert hours["detail"] == "9/10 个班已填周节数"
    done = next(s for s in _steps(hour_classes=10) if s["key"] == "hours")
    assert done["done"]


def test_history_hint_when_current_term_empty_but_history_exists():
    steps = _steps(
        class_total=10, hour_classes=0, teacher_count=0,
        history_year="2025-2026", history_hour_classes=12,
    )
    hours = next(s for s in steps if s["key"] == "hours")
    assert not hours["done"]
    assert "2025-2026" in hours["detail"] and "12 个班" in hours["detail"]
    assignments = next(s for s in steps if s["key"] == "assignments")
    assert "2025-2026" in assignments["detail"]
    # 当前学期已有部分数据时不打扰，仍显示进度
    plain = next(s for s in _steps(hour_classes=4, history_year="2025-2026", history_hour_classes=12) if s["key"] == "hours")
    assert plain["detail"] == "4/10 个班已填周节数"
