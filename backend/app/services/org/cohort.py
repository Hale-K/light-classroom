"""届(cohort)推导。

系统中的“届”统一表示入学届，与组织架构「N届高X年级部」一致：
届 = 学年起始年 - 年级层级 + 1。
例如 2026-2027 学年：高一为 2026 届、高二为 2025 届、高三为 2024 届。
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import TenantConfig


async def current_academic_year(session: AsyncSession, tenant_id: int) -> str:
    """当前学年:优先读租户配置 academic_years.current_academic_year,缺省按日期推(8 月起为新学年)。"""
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()
    if row is not None and isinstance(row.config_value, dict):
        year = row.config_value.get("current_academic_year")
        if isinstance(year, str) and "-" in year:
            return year
    today = date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{start + 1}"


def expected_cohort_label(academic_year: str, grade_level: int) -> str:
    start = int(academic_year.split("-")[0])
    return str(start - grade_level + 1)


def normalize_cohort_label(value: str | None) -> str | None:
    """容错:'2029届'、' 2029 ' 都归一为 '2029'。"""
    if value is None:
        return None
    cleaned = value.strip().removesuffix("届").strip()
    return cleaned or None


def cohort_labels_match(value: str | None, expected: str | None) -> bool:
    """Compare cohort labels in their canonical form, accepting display text such as ``2026届``."""
    return normalize_cohort_label(value) == normalize_cohort_label(expected)
