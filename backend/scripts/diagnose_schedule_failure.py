"""Read-only diagnostics for the newest (or selected) failed scheduling job.

Run from ``backend`` with the project's virtualenv:
    .venv/Scripts/python.exe scripts/diagnose_schedule_failure.py
    .venv/Scripts/python.exe scripts/diagnose_schedule_failure.py --job-id <id>

The script never changes database rows or Redis keys. It combines the durable
request/error record with Redis progress events when those events are available.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.scheduling import SchedulingGenerateJob


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _local_time(value: datetime | None) -> str:
    if value is None:
        return "未知"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


def _event_lines(job_id: str) -> list[dict[str, Any]]:
    try:
        import redis

        client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2,
        )
        raw_events = client.lrange(f"lc:sched:ev:{job_id}", 0, -1)
        return [json.loads(raw) for raw in raw_events]
    except Exception as exc:  # Redis is an optional live event cache.
        print(f"实时事件：不可读取（{type(exc).__name__}: {exc}）")
        return []


async def _load_job(job_id: str | None) -> SchedulingGenerateJob | None:
    async with AsyncSessionLocal() as session:
        stmt = select(SchedulingGenerateJob)
        if job_id:
            stmt = stmt.where(SchedulingGenerateJob.id == job_id)
        else:
            stmt = stmt.where(SchedulingGenerateJob.status == "error").order_by(
                SchedulingGenerateJob.created_at.desc()
            ).limit(1)
        return (await session.execute(stmt)).scalars().first()


def _print_event_analysis(events: list[dict[str, Any]]) -> tuple[int, int]:
    messages = [
        str(event.get("message") or "")
        for event in events
        if event.get("type") == "progress"
    ]
    day_solutions: dict[str, tuple[int, float]] = {}
    for message in messages:
        match = re.search(
            r"seed=(\d+).*白天课求解结束：(?:OPTIMAL|FEASIBLE)，耗时 ([\d.]+)s，可行解 (\d+) 个",
            message,
        )
        if match:
            day_solutions[match.group(1)] = (int(match.group(3)), float(match.group(2)))
    evening_infeasible_seeds: set[str] = set()
    evening_timeout_seeds: set[str] = set()
    excluded_by_attempt: dict[int, int] = {}
    seeds: list[str] = []
    for message in messages:
        match = re.search(r"开始第 \d+/\d+ 轮求解（时限\d+s，seed=(\d+)）", message)
        if match:
            seeds.append(match.group(1))
        seed_match = re.search(r"seed=(\d+)", message)
        seed = seed_match.group(1) if seed_match else None
        if seed and "晚课 INFEASIBLE" in message:
            evening_infeasible_seeds.add(seed)
        if seed and "晚课超时" in message:
            evening_timeout_seeds.add(seed)
        excluded = re.search(r"第 (\d+)/\d+ 次.*已排除 (\d+) 个晚课不兼容方案", message)
        if excluded:
            attempt, count = map(int, excluded.groups())
            excluded_by_attempt[attempt] = max(count, excluded_by_attempt.get(attempt, 0))

    print("\n求解过程")
    print(f"  白天候选尝试：{len(set(seeds))} 次；不同 seed：{len(set(seeds))} 个")
    if day_solutions:
        print(
            "  白天首解耗时："
            + ", ".join(
                f"{seconds:g}s（{count} 个解）"
                for count, seconds in day_solutions.values()
            )
        )
    print(
        f"  晚课模型证明候选无解：{len(evening_infeasible_seeds)} 次；"
        f"晚课超时：{len(evening_timeout_seeds)} 次"
    )
    if excluded_by_attempt:
        print("  每轮开始时已排除：" + ", ".join(
            f"第{attempt}轮 {count} 个" for attempt, count in sorted(excluded_by_attempt.items())
        ))
    else:
        print("  排除数：事件中无记录（可能是旧版本任务或 Redis 事件已过期）")

    print("\n判断边界")
    if evening_infeasible_seeds and not evening_timeout_seeds:
        print("  晚课 INFEASIBLE 只证明对应白天候选无解；不能证明所有白天/晚课组合整体无解。")
        print("  需要将被拒绝的白天课位与晚课冲突规则关联，或运行联合模型，才能确认整体是否可行。")
    elif evening_timeout_seeds:
        print("  存在晚课求解超时；这是未能在时限内找到解，不等同于已证明无解。")
    elif day_solutions:
        print("  该任务没有可供判断的晚课 INFEASIBLE 证明；请检查事件是否完整。")
    return len(set(seeds)), len(evening_infeasible_seeds)


async def main() -> int:
    parser = argparse.ArgumentParser(description="只读分析排课失败任务")
    parser.add_argument("--job-id", help="排课任务 ID；默认分析最近一次失败任务")
    args = parser.parse_args()

    try:
        job = await _load_job(args.job_id)
    except Exception as exc:
        print(f"数据库读取失败：{type(exc).__name__}: {exc}")
        return 2
    if job is None:
        print("没有找到匹配的排课任务。")
        return 1

    payload = job.payload or {}
    odd = payload.get("evening_daily_periods_odd") or []
    even = payload.get("evening_daily_periods_even") or []
    classes = payload.get("class_ids")
    error = job.error or {}
    diagnosis = error.get("diagnosis") if isinstance(error, dict) else None
    print("排课失败诊断（只读）")
    print(f"  任务：{job.id}  状态：{job.status}  阶段：{job.stage}")
    print(f"  范围：学年 {job.academic_year} / 学期 {job.term} / 班级 {len(classes) if classes else '全部'}")
    print(f"  创建时间：{_local_time(job.created_at)}（Asia/Shanghai）")
    print(f"  请求参数：求解器={payload.get('solver', 'cpsat')}，天数={payload.get('days') or '默认'}，"
          f"每日课位={payload.get('periods_per_day') or '默认'}，规则组={payload.get('rule_group_id') or '默认'}")
    print(f"  晚自习请求：{sum(odd)} 单周节次 + {sum(even)} 双周节次")
    print(f"  失败摘要：{error.get('message') or job.message}")
    if isinstance(diagnosis, dict):
        print(f"  停滞阶段：{diagnosis.get('stuck_step') or '未知'}")
        reasons = diagnosis.get("reasons") or []
        if reasons:
            print("  系统诊断：")
            for reason in reasons[:5]:
                print(f"    - {reason}")
        suggestions = diagnosis.get("suggestions") or []
        if suggestions:
            print("  规则排查建议（提示项，不是已证明的冲突核）：")
            for item in suggestions[:8]:
                print(
                    f"    - {item.get('rule_id')} {item.get('title')}："
                    f"{item.get('impact') or item.get('reason') or item.get('action_label') or ''}"
                )

    events = _event_lines(job.id)
    if events:
        _print_event_analysis(events)
    else:
        print("\n没有可用的实时阶段事件；只能读取持久化错误摘要。")

    print("\n配置快照说明")
    print("  持久任务记录保存了生成请求和错误，但规则组、任教关系、课时计划及课位结构在运行时从数据库读取。")
    print("  因此历史任务不能保证按原样重放；当前数据库配置可能已在任务结束后变更。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
