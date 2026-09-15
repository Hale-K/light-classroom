"""新手引导准备流程判定：完成阈值与详情文案。"""
from app.api.v1.onboarding import evaluate_steps, teaching_staff_count_query
from app.ai.supervisor.readiness import preparation_guidance
import pytest
from unittest.mock import AsyncMock
from sqlalchemy import create_engine, insert
from app.models.org import User
from app.models.rbac import Role, UserRole


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
        version_count=1, staff_count=14, schedule_count=100,
    )
    kwargs.update(overrides)
    return evaluate_steps(**kwargs)


def test_ready_school_has_all_steps_done():
    steps = _steps()
    assert len(steps) == 10
    assert all(s["done"] for s in steps)
    assert "当前学期已有 100 个排课条目" in steps[-1]["detail"]


def test_first_generation_does_not_require_a_history_version():
    first = next(step for step in _steps(version_count=0, schedule_count=40) if step["key"] == "generate")
    old_history = next(step for step in _steps(version_count=1, schedule_count=0) if step["key"] == "generate")
    assert first["done"]
    assert not old_history["done"]


def test_only_active_teaching_role_accounts_count_as_prepared_teachers():
    engine = create_engine("sqlite://")
    for table in (User.__table__, Role.__table__, UserRole.__table__):
        table.create(engine)
    with engine.begin() as conn:
        conn.execute(insert(User), [
            {"id": 1, "tenant_id": 1, "name": "普通人员", "phone": "10000000001", "password_hash": "x", "role": "teacher", "status": "active", "frozen": False},
            {"id": 2, "tenant_id": 1, "name": "任教教师", "phone": "10000000002", "password_hash": "x", "role": "teacher", "status": "active", "frozen": False},
            {"id": 3, "tenant_id": 1, "name": "停用教师", "phone": "10000000003", "password_hash": "x", "role": "teacher", "status": "disabled", "frozen": False},
            {"id": 4, "tenant_id": 1, "name": "冻结教师", "phone": "10000000004", "password_hash": "x", "role": "teacher", "status": "active", "frozen": True},
        ])
        conn.execute(insert(Role), [
            {"id": 11, "tenant_id": 1, "code": "subject_teacher", "name": "任教老师"},
            {"id": 12, "tenant_id": 1, "code": "academic_director", "name": "教导主任"},
        ])
        conn.execute(insert(UserRole), [
            {"user_id": 1, "role_id": 12},
            {"user_id": 2, "role_id": 11},
            {"user_id": 3, "role_id": 11},
            {"user_id": 4, "role_id": 11},
        ])
        assert conn.execute(teaching_staff_count_query(1)).scalar_one() == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_readiness_stops_before_detailed_checks_when_personnel_missing(monkeypatch):
    from app.api.v1 import onboarding
    from app.ai.agent import assistant_agent
    from app.ai.runtime import AssistantRuntime, ServiceRegistry
    from app.ai.intent import AssistantIntent
    from app.ai.intent import IntentGateway
    from app.ai.intent import IntentDecision

    async def semantic(*args, **kwargs):
        return IntentDecision(AssistantIntent.READINESS, 0.95, "pgvector")

    monkeypatch.setattr(onboarding, "load_onboarding_status", AsyncMock(
        return_value={"data": {"steps": _steps(staff_count=0, room_count=0, enabled_rules=0)}}
    ))
    model = AsyncMock(side_effect=AssertionError("前置缺失不应调用模型"))
    monkeypatch.setattr(assistant_agent, "agent_reply", model)
    services = ServiceRegistry()
    services.register("intent_gateway", IntentGateway(semantic))
    detailed = AsyncMock(side_effect=AssertionError("前置缺失不应进行细项检查"))
    services.register("readiness_supervisor", type("Supervisor", (), {"run": detailed})())
    result = await assistant_agent.handle_assistant_turn(
        None, 1, [{"role": "user", "content": "帮我检查排课准备情况"}],
        runtime=AssistantRuntime(services=services),
    )
    assert result.jumps[0]["path"] == "/staff"
    assert "没有检查对象不等于检查通过" in result.text
    detailed.assert_not_called()
    model.assert_not_called()


def test_new_school_first_steps_incomplete_with_guidance():
    steps = _steps(year=None, staff_count=0, campus_count=0, building_count=0, room_count=0,
                   allocation_rule_count=0, allocated_room_count=0, resource_assigned_class_count=0,
                   grid_configured=False, class_total=0, teacher_count=0,
                   rule_group_count=0, enabled_rules=0, version_count=0, schedule_count=0)
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
    assert "还没有可排课场室" in no_room["detail"]

    complete = next(s for s in _steps(campus_count=1, building_count=2, room_count=12) if s["key"] == "space")
    assert complete["done"]
    assert complete["detail"] == "已有 1 个校区、2 栋楼宇、12 间可排课场室"


def test_preparation_recommends_personnel_before_space_or_rules():
    text, jumps, ready = preparation_guidance(_steps(staff_count=0, room_count=0, enabled_rules=0))
    assert not ready
    assert jumps[0]["path"] == "/staff"
    assert "准备教师人员：当前应处理" in text
    assert "建全空间层级：前置完成后再处理" in text
    assert "配置排课规则：前置完成后再处理" in text


def test_missing_preparation_data_is_not_treated_as_ready():
    text, jumps, ready = preparation_guidance([])
    assert not ready
    assert jumps == []
    assert "无法判断前置条件" in text


def test_preparation_next_link_tracks_first_missing_prerequisite():
    for missing, path in [
        ({"year": None}, "/settings"),
        ({"room_count": 0}, "/campus-buildings?tab=resources"),
        ({"allocated_room_count": 0}, "/campus-buildings?tab=allocation"),
        ({"resource_assigned_class_count": 0}, "/campus-buildings?tab=class-planning"),
        ({"grid_configured": False}, "/scheduling?tab=slots"),
        ({"hour_classes": 0}, "/scheduling?tab=hours"),
        ({"asg_class_count": 1}, "/scheduling?tab=assignments"),
    ]:
        _, jumps, ready = preparation_guidance(_steps(**missing, enabled_rules=0))
        assert not ready
        assert [jump["path"] for jump in jumps] == [path]


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
