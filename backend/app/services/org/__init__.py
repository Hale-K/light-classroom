"""组织领域：租户、机构树、教职工角色、届次与名称规范。"""

from app.services.org.cohort import (
    cohort_labels_match,
    current_academic_year,
    expected_cohort_label,
    normalize_cohort_label,
)
from app.services.org.naming import normalize_entity_name
from app.services.org.organization import build_organization_tree
from app.services.org.staff_roles import (
    ASSIGNABLE_STAFF_ROLES,
    effective_menu_role,
    get_staff_role_codes,
    normalize_staff_roles,
    replace_staff_roles,
)
from app.services.org.tenant import resolve_tenant_id

__all__ = [
    "ASSIGNABLE_STAFF_ROLES",
    "build_organization_tree",
    "cohort_labels_match",
    "current_academic_year",
    "effective_menu_role",
    "expected_cohort_label",
    "get_staff_role_codes",
    "normalize_entity_name",
    "normalize_cohort_label",
    "normalize_staff_roles",
    "replace_staff_roles",
    "resolve_tenant_id",
]
