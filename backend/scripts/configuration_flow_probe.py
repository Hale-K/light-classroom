"""Reproduce configuration flow gaps with disposable, in-memory SQLite only."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlmodel import Session
from app.api.v1.organization import UnitIn, UnitUpdateIn, create_unit, update_unit
from app.api.v1.facilities import target_student_count
from app.models.enums import BaseUserRole, Gender
from app.models.org import Grade, OrganizationUnit, Student
from app.models.facility import Campus
from app.services.org.organization import build_organization_tree


class AsyncFacade:
    """Calls the same endpoint code over a synchronous in-memory test session."""
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    async def get(self, model, key):
        return self.session.get(model, key)

    def add(self, item):
        self.session.add(item)

    async def commit(self):
        self.session.commit()

    async def refresh(self, item):
        self.session.refresh(item)


async def main():
    engine = create_engine('sqlite://')
    for model in (Campus, Grade, OrganizationUnit, Student):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add(Campus(id=1, tenant_id=77, name='合成校区'))
        session.add(Grade(id=10, tenant_id=77, name='高一', level=1, campus_id=1))
        session.add(Student(id=1, tenant_id=77, name='合成学生', gender=Gender.male, campus_id=1, grade_id=10))
        session.add(OrganizationUnit(id=1, tenant_id=77, name='教学部门', unit_type='department'))
        session.add(OrganizationUnit(id=2, tenant_id=77, name='下级部门', unit_type='department', parent_id=1))
        session.commit()
        facade = AsyncFacade(session)
        principal = SimpleNamespace(role=BaseUserRole.director, id=99)
        try:
            await update_unit(1, UnitUpdateIn(parent_id=2), user=principal, tenant_id=77, session=facade)
            cycle_rejected = False
        except HTTPException as exc:
            cycle_rejected = exc.status_code == 422 and '下级组织' in str(exc.detail)
        rows = session.execute(select(OrganizationUnit)).scalars().all()
        cycle_hidden = not build_organization_tree([row.model_dump() for row in rows], {})
        # Endpoint accepts a grade group without a cohort, but allocation UI excludes it.
        unscoped = await create_unit(UnitIn(name='未填届别的年级部', unit_type='grade_group', grade_id=10),
            user=principal, tenant_id=77, session=facade)
        custom = await create_unit(UnitIn(name='新生教学部', unit_type='grade_group', grade_id=10, cohort_label='2026'),
            user=principal, tenant_id=77, session=facade)
        count = await target_student_count(facade, 77, 1, '2026')
        print(json.dumps({
            'storage': 'disposable in-memory SQLite; no school database accessed',
            'endpoint_adapter': 'sync SQL session wrapped for endpoint coroutine calls',
            'descendant_parent_move_rejected': cycle_rejected,
            'cycle_nodes_hidden_from_current_tree': cycle_hidden,
            'grade_group_without_cohort_accepted': unscoped['data']['cohort_label'] is None,
            'custom_named_group_grade_id': custom['data']['grade_id'],
            'actual_students_in_bound_grade': 1,
            'allocation_student_count_for_custom_group_name': count,
        }, ensure_ascii=False, indent=2))
    engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
