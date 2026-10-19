import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.api.v1.admin import SchoolCreate, create_school
from app.models.org import Tenant, TenantConfig, User
from app.services.org.school_stage import (
    EducationStage,
    get_stage_profile,
    get_school_stage,
    stage_menu_options,
)
from app.services.rbac import build_menu, seed_menu_items


def school_payload(**overrides):
    payload = {
        "code": "stage-school",
        "name": "学段测试学校",
        "province": "福建",
        "education_stage": "senior",
        "gaokao_mode": "3+1+2",
        "admin_name": "校长",
        "admin_phone": "18800008888",
        "admin_password": "secret123",
    }
    payload.update(overrides)
    return payload


def menu_items(stage: EducationStage) -> dict[str, dict]:
    options = stage_menu_options(stage)
    groups = build_menu(
        "director",
        "3+1+2",
        menu_items=seed_menu_items(),
        allowed_menu_keys=options.allowed_menu_keys,
        title_overrides=options.title_overrides,
    )
    return {item["key"]: item for group in groups for item in group["children"]}


def teacher_menu_items(stage: EducationStage) -> dict[str, dict]:
    options = stage_menu_options(stage)
    groups = build_menu(
        "teacher",
        "3+1+2",
        menu_items=seed_menu_items(),
        allowed_menu_keys=options.allowed_menu_keys,
        title_overrides=options.title_overrides,
    )
    return {item["key"]: item for group in groups for item in group["children"]}


def test_legacy_school_creation_defaults_to_senior_school():
    payload = school_payload()
    payload.pop("education_stage")

    body = SchoolCreate.model_validate(payload)

    assert body.education_stage == EducationStage.senior
    assert body.gaokao_mode == "3+1+2"


@pytest.mark.parametrize("stage", ["primary", "junior", "higher", "training"])
def test_non_senior_school_does_not_require_gaokao_mode(stage):
    body = SchoolCreate.model_validate(
        school_payload(education_stage=stage, gaokao_mode=None)
    )

    assert body.education_stage.value == stage
    assert body.gaokao_mode is None


def test_senior_school_still_requires_gaokao_mode():
    with pytest.raises(ValidationError):
        SchoolCreate.model_validate(school_payload(gaokao_mode=None))


def test_unknown_education_stage_is_rejected():
    with pytest.raises(ValidationError):
        SchoolCreate.model_validate(school_payload(education_stage="kindergarten"))


@pytest.mark.parametrize("stage", [EducationStage.primary, EducationStage.junior])
def test_basic_education_hides_high_school_subject_choice(stage):
    items = menu_items(stage)

    assert "classes" in items
    assert "scheduling" in items
    assert "gaokao" not in items
    assert "stream-choice" not in items
    assert "teacher-students" not in teacher_menu_items(stage)


def test_senior_school_preserves_subject_choice_and_teacher_review():
    assert "gaokao" in menu_items(EducationStage.senior)
    assert "teacher-students" in teacher_menu_items(EducationStage.senior)


@pytest.mark.parametrize("stage", [EducationStage.higher, EducationStage.training])
def test_higher_and_training_only_show_currently_supported_generic_features(stage):
    items = menu_items(stage)

    assert {"dashboard", "subjects", "staff-accounts", "facilities", "students"}.issubset(items)
    unsupported = {
        "gaokao", "stream-choice", "classes", "scheduling", "seating", "exam-scheduling",
    }
    assert unsupported.isdisjoint(items)


def test_training_uses_training_specific_menu_names():
    items = menu_items(EducationStage.training)

    assert items["subjects"]["title"] == "课程管理"
    assert items["students"]["title"] == "学员档案"
    assert get_stage_profile(EducationStage.training).label == "教培机构"


@pytest.mark.asyncio
async def test_create_school_persists_stage_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.v1.admin.get_password_hash", lambda password: f"hash:{password}")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stage.db'}")
    async with engine.begin() as connection:
        for table in (Tenant.__table__, TenantConfig.__table__, User.__table__):
            await connection.run_sync(table.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        response = await create_school(
            SchoolCreate.model_validate(
                school_payload(education_stage="training", gaokao_mode=None)
            ),
            session,
            None,
        )
        await session.commit()
        tenant = (await session.execute(select(Tenant))).scalar_one()

        assert response["data"]["education_stage"] == "training"
        assert response["data"]["education_stage_label"] == "教培机构"
        assert response["data"]["gaokao_mode"] is None
        assert await get_school_stage(session, tenant.id) is EducationStage.training

    await engine.dispose()
