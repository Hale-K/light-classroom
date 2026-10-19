"""School education-stage configuration and stage-specific navigation policy."""

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import TenantConfig


class EducationStage(str, Enum):
    primary = "primary"
    junior = "junior"
    senior = "senior"
    higher = "higher"
    training = "training"


STAGE_CONFIG_KEY = "education_stage"


@dataclass(frozen=True)
class StageProfile:
    code: EducationStage
    label: str
    gaokao_applicable: bool = False


@dataclass(frozen=True)
class StageMenuOptions:
    allowed_menu_keys: set[str] | None = None
    title_overrides: dict[str, str] = field(default_factory=dict)


STAGE_PROFILES = {
    EducationStage.primary: StageProfile(EducationStage.primary, "小学"),
    EducationStage.junior: StageProfile(EducationStage.junior, "初中"),
    EducationStage.senior: StageProfile(EducationStage.senior, "高中", gaokao_applicable=True),
    EducationStage.higher: StageProfile(EducationStage.higher, "大学"),
    EducationStage.training: StageProfile(EducationStage.training, "教培机构"),
}

ALL_CURRENT_MENU_KEYS = {
    "teacher-courses", "teacher-preparation", "teacher-homework", "teacher-grades",
    "teacher-students", "teacher-classes", "teacher-notices", "dashboard", "settings",
    "ai-providers", "knowledge", "subjects", "staff-accounts", "rbac", "facilities",
    "students", "teacher-profiles", "classes", "gaokao", "stream-choice", "scheduling",
    "courseware", "file-center", "seating", "exam-scheduling", "chart", "practice", "ai",
}
HIGH_SCHOOL_ONLY_MENU_KEYS = {"gaokao", "stream-choice", "teacher-students"}
GENERIC_MENU_KEYS = ALL_CURRENT_MENU_KEYS - HIGH_SCHOOL_ONLY_MENU_KEYS - {
    "classes", "scheduling", "seating", "exam-scheduling",
}


def get_stage_profile(stage: EducationStage | str) -> StageProfile:
    return STAGE_PROFILES[EducationStage(stage)]


def stage_menu_options(stage: EducationStage | str) -> StageMenuOptions:
    stage = EducationStage(stage)
    if stage is EducationStage.senior:
        return StageMenuOptions()
    if stage in {EducationStage.primary, EducationStage.junior}:
        return StageMenuOptions(
            allowed_menu_keys=ALL_CURRENT_MENU_KEYS - HIGH_SCHOOL_ONLY_MENU_KEYS
        )
    overrides = {"subjects": "课程管理"}
    if stage is EducationStage.training:
        overrides["students"] = "学员档案"
    return StageMenuOptions(allowed_menu_keys=GENERIC_MENU_KEYS, title_overrides=overrides)


def _parse_stage(config: TenantConfig | None) -> EducationStage:
    value = config.config_value if config else None
    raw = value.get("stage") if isinstance(value, dict) else None
    try:
        return EducationStage(raw)
    except (TypeError, ValueError):
        return EducationStage.senior


async def get_school_stage(session: AsyncSession, tenant_id: int) -> EducationStage:
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == STAGE_CONFIG_KEY,
    ))).scalars().first()
    return _parse_stage(config)


async def load_school_stages(
    session: AsyncSession, tenant_ids: list[int]
) -> dict[int, EducationStage]:
    if not tenant_ids:
        return {}
    rows = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id.in_(tenant_ids),
        TenantConfig.config_key == STAGE_CONFIG_KEY,
    ))).scalars().all()
    result = {tenant_id: EducationStage.senior for tenant_id in tenant_ids}
    for row in rows:
        result[row.tenant_id] = _parse_stage(row)
    return result


async def save_school_stage(
    session: AsyncSession, tenant_id: int, stage: EducationStage
) -> TenantConfig:
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == STAGE_CONFIG_KEY,
    ))).scalars().first()
    if config is None:
        config = TenantConfig(tenant_id=tenant_id, config_key=STAGE_CONFIG_KEY)
        session.add(config)
    config.config_value = {"stage": stage.value}
    await session.flush()
    return config
