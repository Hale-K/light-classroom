"""调课必须识别走班课位占用：选科走班模式下行政课不能调入走班时段（行政班模式行为不变）。"""
from app.api.v1.scheduling import _evaluate_move_or_swap
from app.models.gaokao import TeachingClassSchedule
from app.models.org import Schedule

GRID = {
    "days": 5,
    "periods_per_day": 7,
    "daily_periods": [7, 7, 7, 7, 7, 0, 0],
    "enable_evening": False,
    "evening_start_period": None,
}


def _admin(row_id: int, weekday: int, period: int, class_id: int = 1, teacher_id: int = 10) -> Schedule:
    return Schedule(id=row_id, tenant_id=1, class_id=class_id, teacher_id=teacher_id, subject_id=1,
                    weekday=weekday, period=period, academic_year="2026-2027", term="2")


def _walk(teaching_class_id: int, weekday: int, period: int, teacher_id: int = 20) -> TeachingClassSchedule:
    return TeachingClassSchedule(id=100 + teaching_class_id, tenant_id=1, teaching_class_id=teaching_class_id,
                                 teacher_id=teacher_id, subject_id=2, academic_year="2026-2027", term="2",
                                 weekday=weekday, period=period)


SOURCE = _admin(1, weekday=1, period=6)
ROWS = [SOURCE, _admin(2, weekday=3, period=3, class_id=1, teacher_id=10)]


def test_admin_mode_without_walk_context_keeps_move():
    # 行政班课表模式：不加载走班占位，目标空位仍可直接挪课
    evaluated = _evaluate_move_or_swap(ROWS, source=SOURCE, target_weekday=4, target_period=5,
                                       target_parity="all", grid=GRID)
    assert evaluated["mode"] == "move"
    assert evaluated["selectable"] is True
    assert evaluated["available"] is True


def test_walk_mode_blocks_moving_admin_into_walk_slot():
    # 修复前走班占位对检查器不可见，同一时段会被当成空位放行，造成学生撞课
    plain = _evaluate_move_or_swap(ROWS, source=SOURCE, target_weekday=4, target_period=5,
                                   target_parity="all", grid=GRID)
    assert plain["mode"] == "move"
    assert plain["selectable"] is True

    walk_context = {"rows": [_walk(11, weekday=4, period=5)]}
    blocked = _evaluate_move_or_swap(ROWS, source=SOURCE, target_weekday=4, target_period=5,
                                     target_parity="all", grid=GRID, walk_context=walk_context)
    assert blocked["selectable"] is False
    assert blocked["available"] is False
    assert "走班课" in blocked["reason"]


def test_walk_rows_at_other_slots_do_not_block():
    walk_context = {"rows": [_walk(11, weekday=2, period=3), _walk(12, weekday=4, period=1)]}
    evaluated = _evaluate_move_or_swap(ROWS, source=SOURCE, target_weekday=4, target_period=5,
                                       target_parity="all", grid=GRID, walk_context=walk_context)
    assert evaluated["selectable"] is True
    assert evaluated["available"] is True
