"""课表 CSV 生成（与前端导出版式一致）。"""
from __future__ import annotations

from typing import Any

DAY_KEYS = [
    {"weekday": 1, "parity": "all"},
    {"weekday": 2, "parity": "all"},
    {"weekday": 3, "parity": "all"},
    {"weekday": 4, "parity": "all"},
    {"weekday": 5, "parity": "all"},
    {"weekday": 6, "parity": "odd"},
    {"weekday": 6, "parity": "even"},
]


def _matches_parity(entry_parity: str | None, column_parity: str) -> bool:
    parity = entry_parity or "all"
    if column_parity == "all":
        return True
    return parity in {"all", column_parity}


def _cell_text(entries: list[dict[str, Any]], weekday: int, period: int, column_parity: str) -> str:
    names = [
        (item.get("subject_name") or "").strip()
        for item in entries
        if item.get("weekday") == weekday
        and item.get("period") == period
        and _matches_parity(item.get("week_parity"), column_parity)
    ]
    names = [name for name in names if name]
    return "·".join(names)


def build_class_csv_block(
    class_name: str,
    entries: list[dict[str, Any]],
    periods: int,
    evening_start_period: int | None,
) -> str:
    evening_start = evening_start_period or (periods + 1)
    headers = ["节\\周", "一", "二", "三", "四", "五", "单六", "双六"]
    lines = [f"班级：{class_name}", ",".join(headers)]

    for period in range(1, periods + 1):
        row = [str(period)]
        for day in DAY_KEYS:
            text = _cell_text(entries, day["weekday"], period, day["parity"])
            row.append(f'"{text.replace(chr(34), chr(34)+chr(34))}"')
        lines.append(",".join(row))

    for evening in (
        {"label": str(evening_start), "parity": "odd"},
        {"label": f"{evening_start}双", "parity": "even"},
    ):
        row = [evening["label"]]
        for day in DAY_KEYS:
            if day["weekday"] == 6 and day["parity"] != evening["parity"]:
                row.append('""')
                continue
            names = [
                (item.get("subject_name") or "").strip()
                for item in entries
                if item.get("weekday") == day["weekday"]
                and int(item.get("period") or 0) >= evening_start
                and _matches_parity(item.get("week_parity"), evening["parity"])
            ]
            text = "·".join([name for name in names if name])
            row.append(f'"{text.replace(chr(34), chr(34)+chr(34))}"')
        lines.append(",".join(row))
    return "\n".join(lines)


def build_timetable_csv(
    items: list[tuple[str, list[dict[str, Any]]]],
    periods: int,
    evening_start_period: int | None,
) -> bytes:
    blocks = [
        build_class_csv_block(class_name, entries, periods, evening_start_period)
        for class_name, entries in items
    ]
    content = "\n\n".join(blocks)
    return ("\ufeff" + content).encode("utf-8")
