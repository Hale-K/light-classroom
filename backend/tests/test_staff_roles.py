import pytest

from app.models.enums import BaseUserRole
from app.services.staff_roles import (
    ASSIGNABLE_STAFF_ROLES,
    effective_menu_role,
    normalize_staff_roles,
)
from app.api.v1.staff import StaffCreateIn
from app.api.v1.organization import get_new_teacher_ids


def test_staff_account_can_be_created_before_position_assignment():
    payload = StaffCreateIn(name="待分配教师", phone="13800000000", password="123456")

    assert payload.roles == []


def test_only_school_staff_roles_can_be_assigned():
    assert [item.code for item in ASSIGNABLE_STAFF_ROLES] == [
        "head_teacher",
        "subject_teacher",
        "academic_director",
    ]
    assert [item.name for item in ASSIGNABLE_STAFF_ROLES] == [
        "班主任",
        "任教老师",
        "教导主任",
    ]


def test_repeated_auto_allocation_only_returns_new_teachers():
    assert get_new_teacher_ids([11, 12, 13], {11, 12}) == [13]
    assert get_new_teacher_ids([11, 12], {11, 12}) == []


def test_auto_allocation_does_not_exceed_requested_count():
    assert len(get_new_teacher_ids([11, 12, 13], {11})) == 2


def test_staff_can_hold_multiple_roles_and_duplicates_are_removed():
    assert normalize_staff_roles([
        "subject_teacher",
        "head_teacher",
        "subject_teacher",
    ]) == ["head_teacher", "subject_teacher"]


def test_unknown_staff_role_is_rejected():
    with pytest.raises(ValueError, match="不支持的教职工角色"):
        normalize_staff_roles(["principal"])


def test_principal_remains_school_admin_and_academic_director_gets_management_menu():
    assert effective_menu_role(BaseUserRole.director, []) == "director"
    assert effective_menu_role(BaseUserRole.teacher, ["academic_director"]) == "academic_director"
    assert effective_menu_role(BaseUserRole.teacher, ["head_teacher", "subject_teacher"]) == "teacher"
