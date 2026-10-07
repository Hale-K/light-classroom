"""Read-only roster feasibility experiment; JSON input contains no credentials.

Run from backend: python scripts/audit_walk_reserved_slots.py < scoped-data.json
This does not connect to or write the database, or generate administrative lessons.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.scheduling.walk_recommendation import recommend_walk_slots


def main():
    data = json.load(sys.stdin)
    classes = data["classes"]
    members = [tuple(row) for row in data["members"]]
    rooms = data["rooms"]
    assert members and all(isinstance(sid, int) for _, sid in members)
    rosters = {c["id"]: {sid for cid, sid in members if cid == c["id"]} for c in classes}
    graph = {c["id"]: set() for c in classes}
    for left in classes:
        for right in classes:
            if left["id"] != right["id"] and (
                rosters[left["id"]] & rosters[right["id"]] or left["teacher_id"] == right["teacher_id"]
            ):
                graph[left["id"]].add(right["id"])
    best = []
    def clique(chosen, candidates):
        nonlocal best
        if len(chosen) + len(candidates) <= len(best):
            return
        if len(chosen) > len(best):
            best = chosen
        while candidates:
            vertex = candidates.pop()
            clique(chosen + [vertex], candidates & graph[vertex])
    clique([], set(graph))
    by_id = {c["id"]: c for c in classes}
    print(json.dumps({"mutually_conflicting_groups": [by_id[c]["name"] for c in best],
                      "clique_required_slots": sum(by_id[c]["weekly_periods"] for c in best)}), flush=True)
    class_groups = {}
    for cid, sid, admin_class in data.get("admin_members", []):
        class_groups.setdefault(admin_class, set()).add(cid)
    common_admin_classes = [name for name, cids in class_groups.items() if set(best) <= cids]
    print(json.dumps({"admin_classes_affected_by_entire_clique": common_admin_classes}), flush=True)
    scenarios = []
    for seventh_days in ([1, 3], [1, 2, 3, 4], [1, 2, 3, 4, 6]):
        slots = [(day, period) for day in range(1, 7) for period in (5, 6)]
        slots += [(day, 7) for day in seventh_days]
        scenarios.append(slots)
    scenarios.append([(day, p) for day in range(1, 7) for p in range(1, 8)])
    for slots in scenarios:
        result = recommend_walk_slots(classes, members, rooms, slots, time_limit=20)
        print(json.dumps({
            "common_slots": len(slots), "status": result["status"],
            "lower_bound": result.get("lower_bound"),
            "placed_group_periods": len(result.get("placements", [])),
            "slots": slots,
        }), flush=True)


if __name__ == "__main__":
    main()
