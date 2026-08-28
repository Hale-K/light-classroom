"""学年滚动的无副作用计算。

这里不读数据库，也不执行写操作，保证设置页可以先展示“将发生什么”，
确认后再由 API 执行。届别编码使用入学年份，例如 2026届。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RolloverPlan:
    source_entry_year: int
    target_entry_year: int
    source_academic_year: str
    target_academic_year: str


def build_rollover_plan(entry_year: int) -> RolloverPlan:
    return RolloverPlan(
        source_entry_year=entry_year,
        target_entry_year=entry_year + 1,
        source_academic_year=f"{entry_year}-{entry_year + 1}",
        target_academic_year=f"{entry_year + 1}-{entry_year + 2}",
    )


def next_grade_level(level: int) -> int | None:
    """高一升高二、高二升高三，高三毕业后不再生成行政班。"""
    return level + 1 if level in (1, 2) else None


def promoted_class_name(name: str, level: int) -> str:
    """保留班号和校区前缀，只把年级从当前级别推进一级。"""
    labels = {1: "高一", 2: "高二", 3: "高三"}
    target = labels.get(next_grade_level(level))
    if not target:
        return name
    for source in labels.values():
        if source in name:
            return name.replace(source, target, 1)
    return name
