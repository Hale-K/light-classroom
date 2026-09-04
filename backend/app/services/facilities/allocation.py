"""Transparent matching rules for assigning rooms to grade cohorts."""
from __future__ import annotations

from typing import Any, Mapping


def room_matches_rule(room: Mapping[str, Any], rule: Mapping[str, Any]) -> bool:
    """Return whether an available room satisfies every configured condition."""
    if room.get("status") != "available":
        return False
    if rule.get("building_id") is not None and room.get("building_id") != rule["building_id"]:
        return False
    if rule.get("floor_from") is not None and room.get("floor", 0) < rule["floor_from"]:
        return False
    if rule.get("floor_to") is not None and room.get("floor", 0) > rule["floor_to"]:
        return False
    if rule.get("min_capacity") is not None and room.get("capacity", 0) < rule["min_capacity"]:
        return False
    if rule.get("room_type") is not None and room.get("room_type") != rule["room_type"]:
        return False
    feature = rule.get("required_feature")
    if feature is not None and feature not in (room.get("features") or []):
        return False
    return True
