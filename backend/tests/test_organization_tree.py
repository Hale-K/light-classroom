from app.services.org.organization import build_organization_tree


def test_build_organization_tree_keeps_persisted_parent_child_structure():
    units = [
        {"id": 2, "parent_id": 1, "name": "2029届年级部", "unit_type": "grade_group", "sort_order": 20},
        {"id": 1, "parent_id": None, "name": "教务处", "unit_type": "department", "sort_order": 10},
        {"id": 3, "parent_id": 2, "name": "高一(1)班", "unit_type": "admin_class", "sort_order": 10},
    ]

    tree = build_organization_tree(units, {1: 2, 2: 1, 3: 3})

    assert [item["name"] for item in tree] == ["教务处"]
    assert tree[0]["member_count"] == 2
    assert tree[0]["children"][0]["name"] == "2029届年级部"
    assert tree[0]["children"][0]["children"][0]["name"] == "高一(1)班"


def test_orphaned_units_are_kept_at_root_instead_of_disappearing():
    tree = build_organization_tree(
        [{"id": 9, "parent_id": 404, "name": "待修复部门", "unit_type": "department", "sort_order": 1}],
        {},
    )

    assert [item["id"] for item in tree] == [9]
