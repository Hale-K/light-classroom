"""Organization tree projection kept independent from persistence and HTTP."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def current_organization_units(
    units: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return active units that do not sit below an archived or cyclic ancestor."""
    by_id = {int(unit["id"]): dict(unit) for unit in units}
    visible: list[dict[str, Any]] = []
    for unit_id, unit in by_id.items():
        if unit.get("status", "active") != "active":
            continue
        parent_id = unit.get("parent_id")
        seen = {unit_id}
        while parent_id is not None and int(parent_id) in by_id:
            parent_id = int(parent_id)
            if parent_id in seen:
                break
            seen.add(parent_id)
            parent = by_id[parent_id]
            if parent.get("status", "active") != "active":
                break
            parent_id = parent.get("parent_id")
        else:
            visible.append(unit)
    return visible


def organization_subtree_ids(
    root_id: int,
    units: Sequence[Mapping[str, Any]],
) -> set[int]:
    """Find a unit and all descendants, including descendants under archived units."""
    children: dict[int, list[int]] = {}
    known_ids: set[int] = set()
    for unit in units:
        unit_id = int(unit["id"])
        known_ids.add(unit_id)
        parent_id = unit.get("parent_id")
        if parent_id is not None:
            children.setdefault(int(parent_id), []).append(unit_id)
    if root_id not in known_ids:
        return set()
    result: set[int] = set()
    pending = [root_id]
    while pending:
        unit_id = pending.pop()
        if unit_id in result:
            continue
        result.add(unit_id)
        pending.extend(children.get(unit_id, []))
    return result


def build_organization_tree(
    units: Sequence[Mapping[str, Any]],
    member_counts: Mapping[int, int],
) -> list[dict[str, Any]]:
    """Build a stable parent-child tree; malformed orphan nodes remain visible at root."""
    visible_units = current_organization_units(units)
    nodes = {
        int(unit["id"]): {
            **dict(unit),
            "member_count": int(member_counts.get(int(unit["id"]), 0)),
            "children": [],
        }
        for unit in visible_units
    }
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(node.get("parent_id"))
        if parent is None or parent is node:
            roots.append(node)
        else:
            parent["children"].append(node)

    def sort_branch(branch: list[dict[str, Any]]) -> None:
        branch.sort(key=lambda item: (int(item.get("sort_order", 0)), int(item["id"])))
        for item in branch:
            sort_branch(item["children"])

    sort_branch(roots)
    return roots
