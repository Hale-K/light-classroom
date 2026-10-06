import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.org import list_classes
from app.models.facility import RoomCohortAllocation
from app.models.gaokao import StudentSubjectChoice
from app.models.org import Class, Student, StudentClassMembership, Subject


def test_class_tracks_use_confirmed_choices_from_the_class_term_and_tenant():
    engine = create_engine("sqlite://")
    models = [Class, Student, StudentClassMembership, Subject, StudentSubjectChoice, RoomCohortAllocation]
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
    with Session(engine) as session:
        session.add_all([Subject(id=1, name="物理"), Subject(id=2, name="历史")])
        for class_id in range(1, 7):
            session.add(Class(id=class_id, tenant_id=7, grade_id=1,
                              name=f"高一（{class_id}）班", academic_year="2026-2027", term="2",
                              cohort_label="2026", home_room_id=100 + class_id))
        for sid, cid in [(1, 1), (2, 2), (3, 3), (4, 3), (5, 5), (6, 6)]:
            session.add(Student(id=sid, tenant_id=7, class_id=cid, name=f"学生{sid}", gender="male"))
            session.add(StudentClassMembership(
                tenant_id=7, student_id=sid, class_id=cid, grade_id=1,
                cohort_label="2026", academic_year="2026-2027", term="2",
            ))
        def choice(sid, subject, **changes):
            values = dict(tenant_id=7, student_id=sid, scheme_id=1,
                          academic_year="2026-2027", effective_term="2",
                          primary_subject_id=subject, status="confirmed")
            values.update(changes)
            return StudentSubjectChoice(**values)
        session.add_all([
            choice(1, 1), choice(2, 2, status="locked"), choice(3, 1), choice(4, 2),
            choice(5, 1, effective_term="1"),  # 上学期选科不能标记本学期
            choice(5, 2, tenant_id=8),  # 其它租户选科不能污染标签
            choice(6, 1, status="draft"),
        ])
        session.add_all([
            RoomCohortAllocation(tenant_id=7, rule_id=1, room_id=101,
                                 cohort_label="2026", academic_year="2026-2027", term="1"),
            RoomCohortAllocation(tenant_id=7, rule_id=1, room_id=102,
                                 cohort_label="2026", academic_year="2026-2027", term="2"),
        ])
        session.commit()

        class AsyncSessionAdapter:
            async def execute(self, statement):
                return session.execute(statement)

        result = asyncio.run(list_classes(grade_id=None, academic_year=None, term=None,
                                          session=AsyncSessionAdapter(), user=object(), tenant_id=7))
        tracks = {row["id"]: row["subject_track"] for row in result["data"]}
        assert tracks == {1: "physics", 2: "history", 3: "mixed",
                          4: "pending", 5: "pending", 6: "pending"}
        resources = {row["id"]: row["resource_assigned"] for row in result["data"]}
        assert resources == {1: False, 2: True, 3: False, 4: False, 5: False, 6: False}
    engine.dispose()
