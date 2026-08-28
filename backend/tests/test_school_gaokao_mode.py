import pytest
from pydantic import ValidationError

from app.api.v1.admin import SchoolCreate
from app.api.v1.gaokao import _resolve_scheme_mode
from app.services.menu import build_menu


def school_payload(**overrides):
    payload = {
        "code": "strategy-school",
        "name": "策略中学",
        "admin_name": "校长",
        "admin_phone": "18800009999",
        "admin_password": "secret123",
        "province": "广东",
        "gaokao_mode": "3+1+2",
    }
    payload.update(overrides)
    return payload


def test_school_creation_requires_province_and_gaokao_mode():
    with pytest.raises(ValidationError):
        SchoolCreate.model_validate(school_payload(province=None))
    with pytest.raises(ValidationError):
        SchoolCreate.model_validate(school_payload(gaokao_mode=None))


@pytest.mark.parametrize("mode", ["3+1+2", "3+3", "traditional"])
def test_school_creation_accepts_registered_gaokao_modes(mode):
    body = SchoolCreate.model_validate(school_payload(gaokao_mode=mode))
    assert body.gaokao_mode == mode


def test_school_creation_rejects_unknown_gaokao_mode():
    with pytest.raises(ValidationError):
        SchoolCreate.model_validate(school_payload(gaokao_mode="custom"))


def test_new_cohort_inherits_school_mode_and_existing_cohort_keeps_snapshot():
    assert _resolve_scheme_mode(None, None, "3+3") == "3+3"
    assert _resolve_scheme_mode(None, "3+1+2", "3+3") == "3+1+2"
    assert _resolve_scheme_mode("traditional", "3+1+2", "3+3") == "traditional"


def test_menu_capabilities_follow_school_gaokao_mode():
    new_groups = build_menu("director", "3+1+2")
    traditional_groups = build_menu("director", "traditional")
    new_items = {item["key"] for group in new_groups for item in group["children"]}
    traditional_items = {item["key"] for group in traditional_groups for item in group["children"]}

    assert [group["title"] for group in new_groups] == [
        "工作台",
        "学校管理",
        "人员配置",
        "学籍管理",
        "选科走班",
        "教学安排",
        "考试实施",
        "协同办公",
        "资源管理",
    ]
    assert [group["icon"] for group in new_groups] == [
        "dashboard",
        "school",
        "users",
        "file-text",
        "git-branch",
        "book",
        "clipboard",
        "message",
        "building",
    ]
    assert [
        item["key"]
        for group in new_groups
        for item in group["children"]
    ] == [
        "dashboard",
        "settings",
        "staff-accounts",
        "roles",
        "permissions",
        "students",
        "classes",
        "gaokao",
        "scheduling",
        "seating",
        "exams",
        "exam-scheduling",
        "scans",
        "meetings",
        "facilities",
    ]
    assert "gaokao" in new_items
    assert "stream-choice" not in new_items
    assert "gaokao" not in traditional_items
    assert "stream-choice" in traditional_items
    assert "scheduling" in traditional_items
    assert all(item["available"] for group in new_groups for item in group["children"])
    assert {
        "students", "classes", "staff-accounts", "roles", "permissions", "settings"
    }.issubset(new_items)


def test_academic_director_gets_teaching_management_but_not_school_admin_menus():
    groups = build_menu("academic_director", "3+1+2")
    items = {item["key"] for group in groups for item in group["children"]}

    assert {"classes", "scheduling", "gaokao", "exam-scheduling"}.issubset(items)
    assert "organization" not in items
    assert "staff-accounts" not in items
    assert "staff-positions" not in items
    assert "settings" not in items
