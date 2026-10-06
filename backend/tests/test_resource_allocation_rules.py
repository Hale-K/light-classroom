import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock

from app.api.v1 import facilities as facilities_api
from app.api.v1.facilities import ResourceAllocationRuleIn, list_allocation_rules
from app.services.facilities.allocation import room_matches_rule


def test_rule_rejects_an_inverted_floor_range():
    with pytest.raises(ValidationError):
        ResourceAllocationRuleIn(
            name="2029届低楼层教室",
            cohort_label="2029届",
            campus_id=1,
            floor_from=5,
            floor_to=2,
        )


def test_room_matches_all_configured_rule_conditions():
    room = {
        "building_id": 11,
        "floor": 3,
        "capacity": 60,
        "room_type": "classroom",
        "features": ["multimedia"],
        "status": "available",
    }
    rule = {
        "building_id": 11,
        "floor_from": 2,
        "floor_to": 4,
        "min_capacity": 45,
        "room_type": "classroom",
        "required_feature": "multimedia",
    }

    assert room_matches_rule(room, rule)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("building_id", 12),
        ("floor", 5),
        ("capacity", 30),
        ("room_type", "laboratory"),
        ("features", []),
        ("status", "maintenance"),
    ],
)
def test_room_is_rejected_when_any_rule_condition_fails(field, value):
    room = {
        "building_id": 11,
        "floor": 3,
        "capacity": 60,
        "room_type": "classroom",
        "features": ["multimedia"],
        "status": "available",
    }
    room[field] = value
    rule = {
        "building_id": 11,
        "floor_from": 2,
        "floor_to": 4,
        "min_capacity": 45,
        "room_type": "classroom",
        "required_feature": "multimedia",
    }

    assert not room_matches_rule(room, rule)


def test_shared_mode_is_an_explicit_supported_allocation_mode():
    rule = ResourceAllocationRuleIn(
        name="2028届共享多媒体教室",
        cohort_label="2028届",
        campus_id=1,
        allocation_mode="shared",
    )

    assert rule.allocation_mode == "shared"
    assert rule.cohort_label == "2028"


@pytest.mark.asyncio
async def test_allocation_rule_list_is_scoped_to_academic_year_and_term():
    rules_result = MagicMock()
    rules_result.scalars.return_value.all.return_value = []
    counts_result = MagicMock()
    counts_result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[rules_result, counts_result])

    await list_allocation_rules(
        academic_year="2026-2027",
        term="2",
        tenant_id=1,
        session=session,
        user=MagicMock(),
    )

    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        params = call.args[0].compile().params
        assert "2026-2027" in params.values()
        assert "2" in params.values()


@pytest.mark.asyncio
async def test_hard_deleting_allocation_releases_term_scoped_student_memberships(monkeypatch):
    rule = MagicMock(academic_year="2026-2027", term="2")
    allocation = MagicMock(room_id=100)
    class_row = MagicMock(id=10, home_room_id=100)
    legacy_student = MagicMock(id=1, class_id=10)
    membership = MagicMock(student_id=2, status="active")

    def result_with_rows(rows):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[
        result_with_rows([allocation]),
        result_with_rows([class_row]),
        result_with_rows([legacy_student]),
        result_with_rows([membership]),
        result_with_rows([]),
    ])
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(facilities_api, "require_manager", AsyncMock())
    monkeypatch.setattr(facilities_api, "tenant_item", AsyncMock(return_value=rule))

    result = await facilities_api.delete_allocation_rule(
        rule_id=5, tenant_id=7, session=session, user=MagicMock(),
    )

    assert result["data"]["released_student_count"] == 2
    assert legacy_student.class_id is None
    assert membership.status == "removed"
    assert class_row.home_room_id is None
    session.commit.assert_awaited_once()
