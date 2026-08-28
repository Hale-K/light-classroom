"""Organization tree projection kept independent from persistence and HTTP."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_organization_tree(
    units: Sequence[Mapping[str, Any]],
    member_counts: Mapping[int, int],
) -> list[dict[str, Any]]:
    """Build a stable parent-child tree; malformed orphan nodes remain visible at root."""
    nodes = {
        int(unit["id"]): {
            **dict(unit),
            "member_count": int(member_counts.get(int(unit["id"]), 0)),
            "children": [],
        }
        for unit in units
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
