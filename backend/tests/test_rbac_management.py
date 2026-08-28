import pytest
from pydantic import ValidationError

from app.api.v1.rbac import RoleIn, RoleMembersIn
from app.main import app
from app.models.rbac import Role
from app.services.rbac import role_belongs_to_tenant
from app.services.menu import build_menu


def menu_paths(items):
    return {
        child["path"]
        for group in items
        for child in group.get("children", [])
        if child.get("path")
    }


def test_rbac_routes_are_registered_in_the_application():
    paths = set(app.openapi()["paths"])

    assert "/api/v1/rbac/roles" in paths
    assert "/api/v1/rbac/permissions" in paths


def test_custom_role_code_uses_a_stable_machine_readable_format():
    payload = RoleIn(code="teaching_assistant", name="教务助理")

    assert payload.code == "teaching_assistant"
    with pytest.raises(ValidationError):
        RoleIn(code="教务 助理", name="教务助理")


def test_role_members_are_normalized_to_unique_user_ids():
    payload = RoleMembersIn(user_ids=[9, 3, 9, 5])

    assert payload.user_ids == [3, 5, 9]


def test_custom_roles_belong_to_one_school():
    role = Role(code="teaching_assistant", name="教务助理", tenant_id=3)

    assert role.tenant_id == 3


def test_role_access_is_restricted_to_its_school():
    role = Role(code="teaching_assistant", name="教务助理", tenant_id=3)

    assert role_belongs_to_tenant(role, 3)
    assert not role_belongs_to_tenant(role, 4)


def test_permission_codes_drive_the_non_admin_menu():
    paths = menu_paths(build_menu(
        "teacher",
        "3+1+2",
        permission_codes={"dashboard:view", "scheduling:view"},
    ))

    assert paths == {"/dashboard", "/scheduling"}
