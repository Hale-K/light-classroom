"""历史数据体检：只读校验助手/引导新功能所依赖的数据形态，不做任何写入。

用法（backend 目录下）：.venv/Scripts/python.exe scripts/audit_history_data.py
逐租户输出 OK / WARN / FAIL；有 FAIL 时退出码为 1，可直接挂到部署前检查。
覆盖面即新功能的全部读取面：规则组目录、课位网格、学年学期配置、课表版本历史、
校区状态、课时学年格式、任教空引用、ai_* 三表存在性、引导跳过标记。
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import distinct, select

from app.db.session import AsyncSessionLocal
from app.models.facility import Campus
from app.models.org import Class, CourseHourPlan, TeachingAssignment, TenantConfig

RULE_KEY = "scheduling_rule_group"
GRID_KEY = "scheduling_grid_config"
VERSION_KEY = "scheduling_version_history"
GUIDE_KEY = "onboarding_guide"

RESULTS: list[tuple[str, str, str]] = []  # (级别, 租户, 说明)


def record(level: str, tenant: int | str, msg: str) -> None:
    RESULTS.append((level, str(tenant), msg))


def check_rule_scope(tenant: int, scope: str, value: object) -> None:
    from app.services.scheduling.rules import parse_stored_rule_groups

    if not isinstance(value, dict):
        record("FAIL", tenant, f"规则组 {scope} 载荷不是 dict（{type(value).__name__}）")
        return
    try:
        groups, _active = parse_stored_rule_groups(value)
    except Exception as exc:  # noqa: BLE001
        record("FAIL", tenant, f"规则组 {scope} 解析失败：{exc}")
        return
    record("OK", tenant, f"规则组 {scope}：{len(groups)} 组")


def check_version_history(tenant: int, raw: object) -> None:
    if raw is None:
        record("OK", tenant, "课表版本历史：无（引导第六步按未完成计）")
        return
    items = []
    if isinstance(raw, list):
        items = [v for v in raw if isinstance(v, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("versions"), list):
        items = [v for v in raw["versions"] if isinstance(v, dict)]
    else:
        record("FAIL", tenant, f"课表版本历史形态无法解析（{type(raw).__name__}）")
        return
    record("OK", tenant, f"课表版本历史：{len(items)} 个版本")


async def audit_tenant(tenant: int) -> None:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(TenantConfig).where(
            TenantConfig.tenant_id == tenant,
        ))).scalars().all()
        for row in rows:
            value = row.config_value
            if row.config_key == RULE_KEY and isinstance(value, dict):
                for scope, payload in value.items():
                    if isinstance(scope, str) and ":" in scope:
                        check_rule_scope(tenant, scope, payload)
            elif row.config_key == GRID_KEY:
                if value is None:
                    record("WARN", tenant, "课位网格未配置（引导第三步按未完成计，属正常）")
                elif isinstance(value, dict):
                    bad = [
                        scope for scope, cfg in value.items()
                        if isinstance(cfg, dict) and (
                            not isinstance(cfg.get("daily_periods"), list)
                            or len(cfg["daily_periods"]) != 7
                        )
                    ]
                    if bad:
                        record("FAIL", tenant, f"网格 {bad} 的 daily_periods 不是 7 位列表")
                    else:
                        record("OK", tenant, "课位网格形态正常")
            elif row.config_key == VERSION_KEY:
                check_version_history(tenant, value)
            elif row.config_key == GUIDE_KEY:
                if not isinstance(value, dict):
                    record("WARN", tenant, "引导跳过标记不是 dict，将按未跳过处理")

        years = (await session.execute(
            select(distinct(CourseHourPlan.academic_year))
            .where(CourseHourPlan.tenant_id == tenant)
        )).scalars().all()
        odd = [y for y in years if not (y and "-" in y and len(y) >= 9)]
        if odd:
            record("FAIL", tenant, f"课时学年格式异常：{odd}")
        else:
            record("OK", tenant, f"课时学年格式正常（{len(years)} 个学年）")

        null_teacher = (await session.execute(
            select(TeachingAssignment.id).where(
                TeachingAssignment.tenant_id == tenant,
                TeachingAssignment.teacher_id.is_(None),
            ).limit(5)
        )).scalars().all()
        if null_teacher:
            record("WARN", tenant, f"存在未指派教师的任教关系（如 {null_teacher}），引导与草稿会跳过它们")
        else:
            record("OK", tenant, "任教关系无空教师引用")

        campus_statuses = (await session.execute(
            select(distinct(Campus.status)).where(Campus.tenant_id == tenant)
        )).scalars().all()
        weird = [s for s in campus_statuses if s != "active"]
        if weird:
            record("WARN", tenant, f"校区存在非 active 状态：{weird}（引导只统计 active）")
        else:
            record("OK", tenant, f"校区状态正常（{len(campus_statuses)} 种）")

        class_no_campus = (await session.execute(
            select(Class.id).where(Class.tenant_id == tenant, Class.campus_id.is_(None)).limit(1)
        )).scalars().first()
        if class_no_campus is not None:
            record("WARN", tenant, f"存在未挂校区的行政班（如 id={class_no_campus}），不影响引导统计")
        else:
            record("OK", tenant, "行政班均已挂校区")


async def main() -> int:
    async with AsyncSessionLocal() as session:
        tenants = sorted({
            tid for (tid,) in (await session.execute(select(distinct(TenantConfig.tenant_id)))).all()
            if tid is not None
        })
        class_tenants = sorted({
            tid for (tid,) in (await session.execute(select(distinct(Class.tenant_id)))).all()
            if tid is not None
        })
    for tenant in sorted(set(tenants) | set(class_tenants)):
        await audit_tenant(tenant)

    # ai_* 三表存在性（全库一次）
    async with AsyncSessionLocal() as session:
        for table in ("ai_provider", "ai_action", "ai_run"):
            try:
                from sqlalchemy import text
                await session.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))
                record("OK", "-", f"表 {table} 存在")
            except Exception as exc:  # noqa: BLE001
                record("FAIL", "-", f"表 {table} 缺失或不可查：{exc}")

    fails = 0
    for level, tenant, msg in RESULTS:
        print(f"[{level}] 租户{tenant} {msg}")
        if level == "FAIL":
            fails += 1
    print(f"\n共 {len(RESULTS)} 项检查，FAIL {fails} 项。")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
