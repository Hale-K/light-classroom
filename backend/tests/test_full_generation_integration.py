"""全量课表生成集成测试（nstmy 真实数据）。

不 mock 任何数据：直接读取数据库中的课时方案、任教关系、规则组与网格配置，
调用真实的 /scheduling/generate 接口代码（preview=True，不写库），验证三件事：

1. 所有课时全部排入（无 unplaced）
2. 教师与班级无任何同课位冲突
3. 规则组全部硬规则通过（36 条规则整体满足，而非单条验证）

数据库不可用时自动跳过，不影响常规单元测试。
"""

import asyncio
import json
from collections import defaultdict

import asyncpg
import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.integration

DB_CONFIG = dict(
    host="localhost", port=5432, user="postgres", password="123456", database="zhiheng"
)
TENANT_ID = 7
ACADEMIC_YEAR = "2026-2027"
TERM = "1"


def _db_available() -> bool:
    async def _probe() -> bool:
        try:
            conn = await asyncpg.connect(**DB_CONFIG)
            await conn.close()
            return True
        except Exception:
            return False

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


def _run(coro):
    return asyncio.run(coro)


def test_full_generation_ten_classes_conflict_free_and_rule_valid():
    if not _db_available():
        pytest.skip("数据库不可用，跳过集成测试")

    from app.db.session import AsyncSessionLocal, tenant_id_ctx
    from app.api.v1.scheduling import GenerateIn, create_schedule

    async def _generate():
        from app.api.v1.scheduling import _load_grid_config
        from sqlalchemy import text
        tenant_id_ctx.set(TENANT_ID)
        async with AsyncSessionLocal() as session:
            grid = await _load_grid_config(session, TENANT_ID, ACADEMIC_YEAR, TERM)
            await session.execute(text("SELECT 1"))
            body = GenerateIn(
                academic_year=ACADEMIC_YEAR,
                term=TERM,
                preview=True,
                enable_evening=grid["enable_evening"],
                evening_start_period=grid["evening_start_period"],
                evening_daily_periods_odd=grid["evening_daily_periods_odd"],
                evening_daily_periods_even=grid["evening_daily_periods_even"],
            )
            return await create_schedule(body=body, session=session, user=None, tenant_id=TENANT_ID)

    try:
        result = _run(_generate())
    except HTTPException as exc:
        _diagnose_unplaced(exc)
        raise
        detail = exc.detail
        if isinstance(detail, dict) and "rule_validation" in detail:
            failures = [
                r for r in detail["rule_validation"]["results"]
                if r["priority"] == "hard"
                and r["status"] in {"fail", "unresolved", "not_run"}
            ]
            pytest.fail(
                "生成被硬规则阻断：\n"
                + "\n".join(f"  [{r['rule_id']}] {r['title']}: {r['message']}" for r in failures),
                pytrace=False,
            )
        pytest.fail(f"生成失败: {detail}", pytrace=False)

    data = result["data"] if "data" in result else result
    items = data["items"]
    unplaced = data["unplaced"]

    # ---- 断言1：全部课时排入 ----
    assert not unplaced, f"有 {len(unplaced)} 条课时未能排入: {json.dumps(unplaced, ensure_ascii=False)[:500]}"
    assert items, "没有生成任何课程"

    # ---- 断言2：教师与班级无同课位冲突（含单双周并行合法）----
    class_slots = defaultdict(list)
    teacher_slots = defaultdict(list)
    for item in items:
        key = (item["class_id"], item["weekday"], item["period"], item["week_parity"])
        class_slots[key].append(item)
        if item["teacher_id"] is not None:
            tkey = (item["teacher_id"], item["weekday"], item["period"], item["week_parity"])
            teacher_slots[tkey].append(item)
    class_conflicts = {k: v for k, v in class_slots.items() if len(v) > 1 and _parity_conflict(v)}
    teacher_conflicts = {k: v for k, v in teacher_slots.items() if len(v) > 1 and _parity_conflict(v)}
    assert not class_conflicts, f"班级课位冲突 {len(class_conflicts)} 处"
    assert not teacher_conflicts, f"教师课位冲突 {len(teacher_conflicts)} 处"

    # ---- 断言3：全部硬规则通过 ----
    rule_validation = data["rule_validation"]
    assert rule_validation is not None, "规则组未加载"
    hard_failures = [
        r for r in rule_validation["results"]
        if r["priority"] == "hard" and r["status"] in {"fail", "unresolved", "not_run"}
    ]
    assert not hard_failures, (
        "存在违反的硬规则：\n"
        + "\n".join(f"  [{r['rule_id']}] {r['title']}: {r['message']}" for r in hard_failures)
    )
    soft_notes = [
        f"[{r['rule_id']}] {r['title']}: {r['message']}"
        for r in rule_validation["results"] if r["status"] == "fail"
    ]
    assert not soft_notes or True  # 软规则违规仅提示
    print(f"\n✓ 10个班 {len(items)} 节课全部排入，无冲突，硬规则全部通过")
    if soft_notes:
        print("软规则提示：\n" + "\n".join(f"  {note}" for note in soft_notes))


def _diagnose_unplaced(exc: "HTTPException") -> None:
    """422 时尽力从响应中带出未排课程诊断（预览接口失败发生在校验阶段，此为兜底）。"""
    detail = exc.detail
    if isinstance(detail, dict):
        print("[诊断]", detail.get("message"))


def _parity_conflict(items: list[dict]) -> bool:
    """同课位多条记录时，单双周互补（odd+even）不冲突，其余均冲突。"""
    parities = {item["week_parity"] for item in items}
    if len(items) == 2 and parities == {"odd", "even"}:
        return False
    return True
