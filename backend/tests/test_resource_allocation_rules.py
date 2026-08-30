import pytest
from pydantic import ValidationError

from app.api.v1.facilities import ResourceAllocationRuleIn
from app.services.resource_allocation import room_matches_rule


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
