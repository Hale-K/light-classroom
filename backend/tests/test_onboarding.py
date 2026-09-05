"""新手引导六步判定：完成阈值与详情文案。"""
from app.api.v1.onboarding import evaluate_steps


def _steps(**overrides):
    kwargs = dict(
        year="2026-2027", term="1",
        campus_count=2,
        grid_configured=True, grid_line="5 天 × 7 节，含晚自习",
        class_total=10, hour_classes=10,
        teacher_count=14, asg_class_count=10,
        rule_group_count=2, enabled_rules=43,
        version_count=1,
    )
    kwargs.update(overrides)
    return evaluate_steps(**kwargs)


def test_ready_school_has_all_six_done():
    steps = _steps()
    assert len(steps) == 7
    assert all(s["done"] for s in steps)
    assert steps[-1]["detail"] == "已有 1 个课表版本"


def test_new_school_first_steps_incomplete_with_guidance():
    steps = _steps(year=None, campus_count=0, grid_configured=False, class_total=0, teacher_count=0,
                   rule_group_count=0, enabled_rules=0, version_count=0)
    assert not any(s["done"] for s in steps)
    assert "先到空间资源创建校区" in steps[0]["detail"]
    assert "还没有设置当前学年学期" in steps[1]["detail"]
    assert "先到班级管理建班" in steps[3]["detail"]
    assert "还没有教师和班的对应关系" in steps[4]["detail"]


def test_campus_step_done_when_any_active_campus():
    steps = _steps(campus_count=1)
    campus = next(s for s in steps if s["key"] == "campus")
    assert campus["done"]
    assert campus["detail"] == "已有 1 个校区"


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
