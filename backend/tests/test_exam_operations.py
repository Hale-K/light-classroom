"""Exam operations use real persisted schedules, resources and candidate seats."""
import asyncio
from datetime import date

import httpx
import pytest
import json
from fastapi import FastAPI
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.deps import get_current_tenant, get_current_user
from app.api.v1.exam_scheduling import router
from app.db.session import get_session
from app.models.exam import (
    Exam, ExamCandidateAssignment, ExamInvigilatorAvailability, ExamRoom,
    ExamRoomAssignment, ExamSchedule, ExamSchedulingConfig, ExamVenue,
)
from app.models.gaokao import StudentSubjectChoice
from app.models.facility import Campus, Building, Room
from app.models.org import Class, CourseHourPlan, Grade, Student, Subject, TeachingAssignment, Tenant, TenantConfig, User
from app.services.scheduling import arrange_exam_candidates, generate_exam_schedule, ExamRoomResource


def test_agent_exam_capacity_uses_exam_seats_and_simultaneous_workload():
    from app.ai.tools.school.exams import calculate_capacity
    result = json.loads(calculate_capacity(json.dumps({'simultaneous_candidates':1000,
        'usable_seats_per_room':30,'invigilators_per_room':2,'basis':'用户明确的考试规则'})))
    assert result['data']['rooms_required'] == 34
    assert result['data']['simultaneous_invigilators_required'] == 68
    assert result['data']['unused_seats'] == 20
    assert not json.loads(calculate_capacity('{"simultaneous_candidates":1000}'))['ok']


@pytest.mark.asyncio
@pytest.mark.parametrize('view', ['overview', 'calendar', 'rooms', 'teachers', 'candidates', 'checks'])
async def test_agent_exam_tools_read_real_plan_without_writes(exam_api, view):
    from app.ai.tools.school import execute_school_tool
    _, db = exam_api
    class ReadOnly:
        async def execute(self, stmt):
            assert stmt.is_select
            return db.execute(stmt)
    result = json.loads(await execute_school_tool('lookup_exam_operations',
        json.dumps({'exam_id': 1, 'view': view, 'limit': 1}), session=ReadOnly(), tenant_id=7))
    assert result['ok'], result
    assert result['scope']['exam_id'] == 1
    assert result['scope']['academic_year'] == '2026-2027'
    data = result['data']
    if view == 'overview':
        assert data['distinct_candidates'] == 3
        assert data['room_session_count'] == 2
        assert data['configuration']['candidate_mode'] == 'grade'
    elif view == 'checks':
        assert isinstance(data['passed'], bool)
    else:
        assert data['returned'] == 1
        assert data['has_more'] == (data['total'] > 1)


@pytest.mark.asyncio
async def test_agent_exam_tool_requires_scope_and_isolates_tenants(exam_api):
    from app.ai.tools.school.exams import execute
    _, db = exam_api
    class ReadOnly:
        async def execute(self, stmt):
            assert stmt.is_select
            return db.execute(stmt)
    adapter = ReadOnly()
    for args in ({'view':'overview'}, {'view':'overview','exam_id':99},
                 {'view':'overview','exam_id':1,'term':'2'}):
        result = json.loads(await execute(json.dumps(args), session=adapter, tenant_id=7))
        assert not result['ok']
        assert result['code'] == 'MISSING_SCOPE'
    result = json.loads(await execute('{"view":"exams"}', session=adapter, tenant_id=7))
    assert all(e['exam_id'] != 99 for e in result['data']['items'])


@pytest.mark.asyncio
async def test_agent_exam_tool_cannot_bypass_account_permission(monkeypatch):
    from app.ai.gateway.tool import ToolScope
    from app.ai.tools.school import evidence
    from unittest.mock import AsyncMock
    monkeypatch.setattr(evidence, 'authorized', AsyncMock(return_value=False))
    result = json.loads(await ToolScope(None, 7, 1, False, {}).execute(
        'lookup_exam_operations', '{"exam_id":1,"view":"candidates"}'))
    assert result['code'] == 'FORBIDDEN'


@pytest.mark.parametrize('seat_limit', [25, 30])
def test_gaokao_rooms_cap_seats_shuffle_roster_and_keep_limit_after_adjustment(exam_api, seat_limit):
    request, session = exam_api
    for name in ['A', 'B']:
        session.execute(delete(ExamRoom).where(ExamRoom.name == name))
        session.add(ExamRoom(tenant_id=7, name=name, capacity=60))
    session.add(ExamRoom(tenant_id=7, name='E', capacity=60))
    session.add_all([Student(id=i, tenant_id=7, class_id=1, grade_id=1, gender='male',
        name=f'学生{i}', student_no=f'2026{i:03}', roster_order=i) for i in range(4, 35)])
    session.commit()
    body = {'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-10-20',
        'candidate_mode': 'grade', 'schedule_mode': 'custom', 'invigilators_per_room': 2,
        'rules': {'room_mode': 'gaokao', 'room_seat_limit': seat_limit},
        'rooms': [{'name': name, 'capacity': 60} for name in ['A', 'B', 'E']]}
    generated = request('POST', '/plans', json=body)
    assert generated.status_code == 200, generated.text
    rooms = generated.json()['data']['rooms']
    assert len(rooms) == 2
    assert [r['candidate_count'] for r in rooms] == [seat_limit, 34 - seat_limit]
    assert all(r['capacity'] == seat_limit and len(r['invigilator_ids']) == 2 for r in rooms)
    seats = request('GET', '/plans/3/candidates', params={'page_size': 100}).json()['data']['items']
    ordered = sorted(seats, key=lambda c: (c['room_name'], c['seat_no']))
    assert [c['student_id'] for c in ordered] != list(range(1, 35))
    assert {c['student_id'] for c in seats} == set(range(1, 35))
    assert request('GET', '/plans/3/checks').json()['data']['ok']
    assert request('GET', '/plans/3/admission-tickets').json()['data']['pagination']['total'] == 34
    session.add_all([ExamVenue(tenant_id=7, exam_id=3, name=name, capacity=60) for name in ['A', 'B', 'E']])
    session.commit()
    moved = request('PATCH', f"/plans/3/rooms/{rooms[0]['id']}", json={'room_name': 'E'})
    assert moved.status_code == 200, moved.text
    assert session.get(ExamRoomAssignment, rooms[0]['id']).capacity == seat_limit
    refused = request('PATCH', f"/plans/3/candidates/{ordered[0]['id']}",
        json={'room_assignment_id': rooms[0]['id'], 'seat_no': seat_limit + 1})
    assert refused.status_code == 409


def test_gaokao_room_limit_is_used_in_capacity_diagnostics(exam_api):
    request, session = exam_api
    session.add(ExamRoom(tenant_id=7, name='E', capacity=60))
    session.add_all([Student(id=i, tenant_id=7, class_id=1, grade_id=1, gender='male',
        name=f'学生{i}', student_no=f'2026{i:03}', roster_order=i) for i in range(4, 35)])
    session.commit()
    response = request('POST', '/plans/check', json={'exam_id': 3, 'grade_ids': [1],
        'start_date': '2026-10-20', 'rules': {'room_mode': 'gaokao', 'room_seat_limit': 30},
        'rooms': [{'name': 'E', 'capacity': 60}], 'invigilators_per_room': 2})
    assert response.status_code == 422
    assert '可用 30 座' in response.text


def test_gaokao_shuffle_is_stable_across_common_subjects_and_roster_order():
    from app.services.exam_rules import ExamRules, order_exam_rosters
    rules = ExamRules(room_mode='gaokao')
    ordered = order_exam_rosters({1: list(range(1, 61)), 2: list(range(60, 0, -1))}, rules, 42)
    assert ordered[1] == ordered[2]
    assert ordered[1] != list(range(1, 61))
    assert ordered[1] != order_exam_rosters({1: list(range(1, 61))}, rules, 43)[1]


def test_invigilation_reuses_teachers_skipped_for_a_different_subject():
    schedules = generate_exam_schedule([
        {"id": 1, "grade_id": 1, "subject_id": 1, "teacher_id": 10},
        {"id": 2, "grade_id": 2, "subject_id": 1, "teacher_id": 11},
    ], start_date=date(2026, 6, 8), mode="3+1+2", subject_names={1: "语文"})
    plan = arrange_exam_candidates(
        schedules, candidate_ids_by_course={1: [1], 2: [2]},
        rooms=[ExamRoomResource("A", 1), ExamRoomResource("B", 1)],
        teacher_ids=[10, 11], invigilators_per_room=1,
    )
    assert [room.invigilator_ids for room in plan.rooms] == [(11,), (10,)]


def test_invigilation_balances_workload_across_sessions():
    schedules = generate_exam_schedule([
        {"id": index, "grade_id": 1, "subject_id": index} for index in range(1, 5)
    ], start_date=date(2026, 6, 8))
    plan = arrange_exam_candidates(
        schedules, candidate_ids_by_course={i: [1] for i in range(1, 5)},
        rooms=[ExamRoomResource("A", 10)], teacher_ids=[10, 11], invigilators_per_room=1,
    )
    assigned = [room.invigilator_ids[0] for room in plan.rooms]
    assert assigned.count(10) == assigned.count(11) == 2


def test_invigilation_daily_limit_includes_existing_non_overlapping_tasks():
    schedules = generate_exam_schedule([{'id': 1, 'grade_id': 1, 'subject_id': 1}],
                                       start_date=date(2026, 6, 8))
    result = arrange_exam_candidates(schedules, candidate_ids_by_course={1: [1]},
        rooms=[ExamRoomResource('A', 10)], teacher_ids=[10, 11], invigilators_per_room=1,
        teacher_daily_limit=1, existing_daily_workload={(10, date(2026, 6, 8)): 1})
    assert result.rooms[0].invigilator_ids == (11,)
    with pytest.raises(ValueError, match='每日上限'):
        arrange_exam_candidates(schedules, candidate_ids_by_course={1: [1]},
            rooms=[ExamRoomResource('A', 10)], teacher_ids=[10], invigilators_per_room=1,
            teacher_daily_limit=1, existing_daily_workload={(10, date(2026, 6, 8)): 1})


@pytest.fixture
def exam_api():
    engine = create_engine("sqlite://")
    models = [Tenant, TenantConfig, Campus, Building, Room, Grade, Class, Student, Subject, User, CourseHourPlan, TeachingAssignment,
              StudentSubjectChoice, Exam, ExamSchedule, ExamRoom, ExamVenue,
              ExamSchedulingConfig, ExamInvigilatorAvailability,
              ExamRoomAssignment, ExamCandidateAssignment]
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([
            Tenant(id=7, code="exam-test", name="测试学校", gaokao_mode="custom"),
            Grade(id=1, tenant_id=7, name="高一", level=1),
            Class(id=1, tenant_id=7, grade_id=1, name="1班"),
            Subject(id=1, tenant_id=7, name="数学"),
            Exam(id=1, tenant_id=7, name="期中考试", academic_year="2026-2027"),
            Exam(id=2, tenant_id=7, name="另一场考试", academic_year="2026-2027"),
            Exam(id=3, tenant_id=7, name="待生成", academic_year="2026-2027"),
            Exam(id=99, tenant_id=99, name="其他学校", academic_year="2026-2027"),
            ExamSchedulingConfig(tenant_id=7, exam_id=1, grade_ids=[1],
                                 start_date=date(2026, 6, 8), invigilators_per_room=1),
            CourseHourPlan(tenant_id=7, class_id=1, subject_id=1,
                           academic_year="2026-2027", term="1", weekly_periods=5),
            *[User(id=i, tenant_id=7, name=f"教师{i}", phone=str(i), password_hash="unused")
              for i in range(1, 5)],
            *[Student(id=i, tenant_id=7, class_id=1, grade_id=1, gender="male",
                      name=f"学生{i}", student_no=f"202600{i}", roster_order=i)
              for i in range(1, 4)],
            *[ExamRoom(tenant_id=7, name=name, capacity=cap)
              for name, cap in [("A", 2), ("B", 2), ("C", 1), ("D", 4)]],
            *[ExamVenue(tenant_id=7, exam_id=1, name=name, capacity=cap)
              for name, cap in [("A", 2), ("B", 2), ("C", 1), ("D", 4)]],
            ExamSchedule(id=1, tenant_id=7, exam_id=1, grade_id=1, subject_id=1,
                         exam_date=date(2026, 6, 8), session_index=1,
                         start_time="09:00", end_time="11:00"),
            ExamSchedule(id=2, tenant_id=7, exam_id=2, grade_id=1, subject_id=1,
                         exam_date=date(2026, 6, 8), session_index=9,
                         start_time="10:00", end_time="12:00"),
            *[ExamRoomAssignment(id=i, tenant_id=7, exam_id=1, exam_schedule_id=1,
                                 grade_id=1, subject_id=1, exam_date=date(2026, 6, 8),
                                 session_index=1, room_name=name, capacity=2,
                                 candidate_count=count, invigilator_ids=[teacher])
              for i, name, count, teacher in [(1, "A", 2, 1), (2, "B", 1, 2)]],
            ExamRoomAssignment(id=3, tenant_id=7, exam_id=2, exam_schedule_id=2,
                               grade_id=1, subject_id=1, exam_date=date(2026, 6, 8),
                               session_index=9, room_name="C", capacity=1,
                               candidate_count=0, invigilator_ids=[3]),
            *[ExamCandidateAssignment(id=i, tenant_id=7, exam_id=1,
                                      exam_schedule_id=1, exam_room_assignment_id=room,
                                      grade_id=1, subject_id=1, student_id=i,
                                      exam_date=date(2026, 6, 8), session_index=1,
                                      start_time="09:00", end_time="11:00",
                                      room_name=name, seat_no=seat)
              for i, room, name, seat in [(1, 1, "A", 1), (2, 1, "A", 2), (3, 2, "B", 1)]],
        ])
        session.commit()

        class Adapter:
            async def execute(self, stmt): return session.execute(stmt)
            async def get(self, model, key): return session.get(model, key)
            def add(self, item): session.add(item)
            def add_all(self, items): session.add_all(items)
            async def flush(self): session.flush()
            async def commit(self): session.commit()
            async def refresh(self, item): session.refresh(item)
            async def rollback(self): session.rollback()

        app = FastAPI()
        app.include_router(router)
        async def db():
            try:
                yield Adapter()
            except Exception:
                session.rollback()
                raise
        app.dependency_overrides[get_session] = db
        app.dependency_overrides[get_current_tenant] = lambda: 7
        app.dependency_overrides[get_current_user] = lambda: object()

        def request(method, path, **kwargs):
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                            base_url="http://test") as client:
                    return await client.request(method, "/exam-scheduling" + path, **kwargs)
            return asyncio.run(run())
        yield request, session
    engine.dispose()


def test_generation_creates_real_candidate_seats_without_paper_records(exam_api):
    request, _ = exam_api
    response = request("POST", "/plans", json={
        "exam_id": 3, "grade_ids": [1], "start_date": "2026-06-09",
        "rooms": [{"name": "A", "capacity": 2}, {"name": "B", "capacity": 2}],
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["summary"]["candidate_assignment_count"] == 3


def test_replacement_checks_actual_time_overlap_across_exams(exam_api):
    request, session = exam_api
    response = request("PATCH", "/plans/1/rooms/1", json={"invigilator_ids": [3]})
    assert response.status_code == 409, response.text
    assert "监考" in response.json()["detail"]
    assert session.get(ExamRoomAssignment, 1).invigilator_ids == [1]


def test_custom_subject_order_survives_config_save_and_calendar_preview(exam_api):
    request, session = exam_api
    session.add(Subject(id=2, tenant_id=7, name='语文'))
    session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=2, academic_year='2026-2027', term='1', weekly_periods=5))
    session.commit()
    response = request('PUT', '/exams/3/config', json={'grade_ids': [1], 'subject_ids': [2, 1],
        'start_date': '2026-06-10', 'sessions': [{'start_time':'09:00','end_time':'11:00'}, {'start_time':'14:30','end_time':'16:30'}]})
    assert response.status_code == 200, response.text
    preview = request('GET', '/plans/3/preview')
    assert preview.status_code == 200, preview.text
    assert [item['subject_id'] for item in preview.json()['data']] == [2, 1]


def test_weekly_window_applies_to_generation_and_manual_adjustment(exam_api):
    request, session = exam_api
    body = {'enabled': True, 'unavailable_slots': ['weekly#3#13:00#18:00']}
    assert request('PUT', '/exams/3/invigilators/1', json=body).status_code == 200
    generated = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-06-10',
        'sessions': [{'start_time':'14:30','end_time':'16:30'}], 'rooms': [{'name':'A','capacity':2},{'name':'B','capacity':2}]})
    assert generated.status_code == 200, generated.text
    own = session.execute(select(ExamRoomAssignment).where(ExamRoomAssignment.exam_id == 3)).scalars().all()
    assert own and all(1 not in item.invigilator_ids for item in own)
    blocked = request('PATCH', f'/plans/3/rooms/{own[0].id}', json={'invigilator_ids': [1]})
    assert blocked.status_code == 409 and '不能监考' in blocked.text
    assert request('PUT', '/exams/3/invigilators/1', json={'unavailable_slots': ['weekly#3#18:00#13:00']}).status_code == 422


def test_teacher_swap_updates_both_sides_and_rejects_blocked_swap_atomically(exam_api):
    request, session = exam_api
    body = {'first_room_id':1, 'first_teacher_id':1, 'second_room_id':2, 'second_teacher_id':2}
    response = request('POST', '/plans/1/invigilators/swap', json=body)
    assert response.status_code == 200, response.text
    assert session.get(ExamRoomAssignment, 1).invigilator_ids == [2]
    assert session.get(ExamRoomAssignment, 2).invigilator_ids == [1]
    assert request('PUT', '/exams/1/invigilators/1', json={'unavailable_slots':['weekly#1#08:00#12:00']}).status_code == 200
    blocked = request('POST', '/plans/1/invigilators/swap', json={**body, 'first_teacher_id':2, 'second_teacher_id':1})
    assert blocked.status_code == 409, blocked.text
    assert session.get(ExamRoomAssignment, 1).invigilator_ids == [2]
    assert session.get(ExamRoomAssignment, 2).invigilator_ids == [1]
    assert request('POST', '/plans/1/invigilators/swap', json={**body, 'second_room_id':3}).status_code == 404


def test_teacher_swap_across_times_checks_both_new_times(exam_api):
    request, session = exam_api
    session.add(ExamSchedule(id=4, tenant_id=7, exam_id=1, grade_id=1, subject_id=1,
        exam_date=date(2026,6,10), session_index=2, start_time='14:30', end_time='16:30'))
    room = session.get(ExamRoomAssignment, 2)
    room.exam_schedule_id, room.exam_date, room.session_index = 4, date(2026,6,10), 2
    candidate = session.get(ExamCandidateAssignment, 3)
    candidate.exam_schedule_id, candidate.exam_date, candidate.session_index = 4, date(2026,6,10), 2
    candidate.start_time, candidate.end_time = '14:30', '16:30'
    session.commit()
    assert request('PUT', '/exams/1/invigilators/1', json={'unavailable_slots':['weekly#3#13:00#18:00']}).status_code == 200
    body = {'first_room_id':1, 'first_teacher_id':1, 'second_room_id':2, 'second_teacher_id':2}
    response = request('POST', '/plans/1/invigilators/swap', json=body)
    assert response.status_code == 409 and '不能监考' in response.text
    assert session.get(ExamRoomAssignment, 1).invigilator_ids == [1]
    assert session.get(ExamRoomAssignment, 2).invigilator_ids == [2]
    assert request('PUT', '/exams/1/invigilators/1', json={'unavailable_slots':[]}).status_code == 200
    response = request('POST', '/plans/1/invigilators/swap', json=body)
    assert response.status_code == 200, response.text
    assert session.get(ExamRoomAssignment, 1).invigilator_ids == [2]
    assert session.get(ExamRoomAssignment, 2).invigilator_ids == [1]


def test_replacement_rejects_leave_and_duplicate_teachers(exam_api):
    request, session = exam_api
    session.add(ExamInvigilatorAvailability(tenant_id=7, exam_id=1, teacher_id=4,
                leave_start=date(2026, 6, 8), leave_end=date(2026, 6, 8)))
    session.commit()
    assert request("PATCH", "/plans/1/rooms/1", json={"invigilator_ids": [4]}).status_code == 409
    assert request("PATCH", "/plans/1/rooms/1", json={"invigilator_ids": [1, 1]}).status_code == 422


def test_room_replacement_checks_capacity_and_updates_admission_tickets(exam_api):
    request, session = exam_api
    assert request("PATCH", "/plans/1/rooms/1", json={"room_name": "C"}).status_code == 409
    response = request("PATCH", "/plans/1/rooms/1", json={"room_name": "D"})
    assert response.status_code == 200, response.text
    assert session.get(ExamCandidateAssignment, 1).room_name == "D"
    tickets = request("GET", "/plans/1/admission-tickets").json()["data"]["items"]
    assert tickets[0]["sessions"][0]["room_name"] == "D"


def test_seat_move_and_explicit_swap_keep_counts_consistent(exam_api):
    request, session = exam_api
    path = "/plans/1/candidates/1"
    assert request("PATCH", path, json={"room_assignment_id": 2, "seat_no": 1}).status_code == 409
    response = request("PATCH", path, json={"room_assignment_id": 2, "seat_no": 1, "swap": True})
    assert response.status_code == 200, response.text
    assert session.get(ExamCandidateAssignment, 3).exam_room_assignment_id == 1
    response = request("PATCH", path, json={"room_assignment_id": 2, "seat_no": 2})
    assert response.status_code == 200, response.text
    assert session.get(ExamRoomAssignment, 1).candidate_count == 2
    assert session.get(ExamRoomAssignment, 2).candidate_count == 1


def test_ticket_filters_are_per_student_and_number_survives_seat_changes(exam_api):
    request, _ = exam_api
    response = request("GET", "/plans/1/admission-tickets", params={"keyword": "学生1"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] == 1
    ticket = data["items"][0]
    assert ticket["class_name"] == "1班"
    assert ticket["sessions"][0]["subject_name"] == "数学"
    assert ticket["candidate_no"]
    request("PATCH", "/plans/1/candidates/1", json={"room_assignment_id": 2, "seat_no": 2})
    changed = request("GET", "/plans/1/admission-tickets", params={"keyword": "学生1"}).json()["data"]["items"][0]
    assert changed["candidate_no"] == ticket["candidate_no"]


def test_print_and_plan_operations_do_not_expose_other_schools(exam_api):
    request, _ = exam_api
    for path in ["/plans/99", "/plans/99/admission-tickets", "/plans/99/checks"]:
        assert request("GET", path).status_code == 404
    assert request("PATCH", "/plans/99/rooms/1", json={"room_name": "D"}).status_code == 404


def test_invalid_plan_blocks_printing_and_reports_which_room(exam_api):
    request, session = exam_api
    row = session.get(ExamCandidateAssignment, 2)
    row.seat_no = 1
    session.add(row)
    session.commit()
    result = request("GET", "/plans/1/checks")
    assert result.status_code == 200, result.text
    assert not result.json()["data"]["ok"]
    assert any(issue["code"] == "seat_collision" for issue in result.json()["data"]["issues"])
    assert request("GET", "/plans/1/admission-tickets").status_code == 409


def test_multiday_generation_and_preflight_preserve_existing_results(exam_api):
    request, session = exam_api
    for i, name in [(2, '英语'), (3, '语文')]:
        session.add(Subject(id=i, tenant_id=7, name=name))
        session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=i,
                                  academic_year='2026-2027', term='1', weekly_periods=4))
    session.commit()
    body = {'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-06-09',
            'rooms': [{'name': 'D', 'capacity': 4}], 'invigilators_per_room': 1}
    preview = request('POST', '/plans/check', json=body)
    assert preview.status_code == 200, preview.text
    assert not session.execute(select(ExamSchedule).where(ExamSchedule.exam_id == 3)).scalars().all()
    generated = request('POST', '/plans', json=body)
    assert generated.status_code == 200, generated.text
    assert generated.json()['data']['summary']['day_count'] == 2


def test_generation_avoids_other_exam_occupied_rooms_and_teachers(exam_api):
    request, session = exam_api
    # Keep resource reservations, but use a distinct candidate cohort.
    session.execute(delete(ExamCandidateAssignment).where(ExamCandidateAssignment.exam_id == 1))
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1],
        'start_date': '2026-06-08', 'rooms': [{'name': 'A', 'capacity': 2}, {'name': 'D', 'capacity': 4}],
        'invigilators_per_room': 1})
    assert response.status_code == 200, response.text
    room = response.json()['data']['rooms'][0]
    assert room['room_name'] == 'D'
    assert room['invigilator_ids'] == [4]


def test_tickets_pagination_revision_changes_after_adjustment(exam_api):
    request, _ = exam_api
    first = request('GET', '/plans/1/admission-tickets', params={'page_size': 1}).json()['data']
    assert first['pagination']['total_pages'] == 3
    assert len(first['items']) == 1
    request('PATCH', '/plans/1/candidates/1', json={'room_assignment_id': 2, 'seat_no': 2})
    changed = request('GET', '/plans/1/admission-tickets', params={'page_size': 1}).json()['data']
    assert changed['revision'] != first['revision']


def test_school_exam_can_select_subjects_without_elective_confirmation(exam_api):
    request, session = exam_api
    session.add(Subject(id=2, tenant_id=7, name='物理'))
    session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=2, academic_year='2026-2027', term='1', weekly_periods=4))
    session.commit()
    body = {'exam_id': 3, 'grade_ids': [1], 'subject_ids': [2], 'start_date': '2026-06-09',
            'candidate_mode': 'grade', 'schedule_mode': 'custom', 'rooms': [{'name': 'D', 'capacity': 4}]}
    response = request('POST', '/plans', json=body)
    assert response.status_code == 200, response.text
    assert [s['subject_name'] for s in response.json()['data']['schedules']] == ['物理']
    assert response.json()['data']['summary']['student_count'] == 3
    body['candidate_mode'] = 'choices'
    failed = request('POST', '/plans', json=body)
    assert failed.status_code == 422
    assert request('GET', '/plans/3').json()['data']['summary']['student_count'] == 3


def test_seat_adjustment_checks_updated_resource_capacity(exam_api):
    request, session = exam_api
    catalog = session.execute(select(ExamRoom).where(ExamRoom.name == 'B')).scalar_one()
    catalog.capacity = 1
    session.add(catalog); session.commit()
    assert request('PATCH', '/plans/1/candidates/1', json={'room_assignment_id': 2, 'seat_no': 2}).status_code == 409


def test_finished_exam_cannot_be_regenerated_or_adjusted(exam_api):
    request, session = exam_api
    exam = session.get(Exam, 1); exam.status = 'finished'; session.add(exam); session.commit()
    assert request('PATCH', '/plans/1/rooms/1', json={'room_name': 'D'}).status_code == 409
    assert request('POST', '/plans', json={'exam_id': 1, 'start_date': '2026-06-09'}).status_code == 409


def test_changed_config_and_missing_candidate_block_stale_printing(exam_api):
    request, session = exam_api
    config = session.execute(select(ExamSchedulingConfig).where(ExamSchedulingConfig.exam_id == 1)).scalar_one()
    config.start_date = date(2026, 6, 9); session.add(config); session.commit()
    issues = request('GET', '/plans/1/checks').json()['data']['issues']
    assert any(i['code'] == 'config_changed' for i in issues)
    assert request('GET', '/plans/1/admission-tickets').status_code == 409
    session.delete(session.get(ExamCandidateAssignment, 3))
    room = session.get(ExamRoomAssignment, 2); room.candidate_count = 0; session.add(room); session.commit()
    issues = request('GET', '/plans/1/checks').json()['data']['issues']
    assert any(i['code'] == 'missing_candidate' for i in issues)

def test_rules_persist_and_validate_ranges(exam_api):
    request, _ = exam_api
    rules = {'room_mode': 'school', 'room_seat_limit': 30, 'student_daily_limit': 2, 'min_break_minutes': 30, 'teacher_daily_limit': 1,
             'avoid_own_subject': True, 'same_subject_same_time': True, 'allow_subject_batches': False}
    response = request('PUT', '/exams/1/config', json={'grade_ids': [1], 'rules': rules})
    assert response.status_code == 200, response.text
    assert request('GET', '/exams/1/config').json()['data']['rules'] == {**rules, 'subject_time_slots': {}, 'reference_mode': 'auto'}
    assert request('PUT', '/exams/1/config', json={'grade_ids': [1], 'rules': {'teacher_daily_limit': 0}}).status_code == 422


def test_student_daily_limit_spreads_exams_across_days(exam_api):
    request, session = exam_api
    for i in (2, 3):
        session.add(Subject(id=i, tenant_id=7, name=f'科目{i}'))
        session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=i, academic_year='2026-2027', term='1', weekly_periods=4))
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-06-09',
        'rooms': [{'name': 'D', 'capacity': 4}], 'rules': {'student_daily_limit': 1}})
    assert response.status_code == 200, response.text
    assert response.json()['data']['summary']['day_count'] == 3
    assert request('GET', '/plans/3/checks').json()['data']['ok']


def test_minimum_break_rejects_short_gap_without_replacing_results(exam_api):
    request, session = exam_api
    session.add(Subject(id=2, tenant_id=7, name='英语'))
    session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=2, academic_year='2026-2027', term='1', weekly_periods=4))
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 1, 'grade_ids': [1], 'start_date': '2026-06-09',
        'sessions': [{'start_time': '09:00', 'end_time': '10:00'}, {'start_time': '10:10', 'end_time': '11:10'}],
        'rules': {'min_break_minutes': 30}})
    assert response.status_code == 422
    assert '休息间隔不足' in response.json()['detail']
    assert session.get(ExamCandidateAssignment, 1).seat_no == 1


def test_same_subject_rule_synchronizes_grades(exam_api):
    request, session = exam_api
    session.add(Grade(id=2, tenant_id=7, name='高二', level=2))
    session.add(Class(id=2, tenant_id=7, grade_id=2, name='2班'))
    session.add(Student(id=4, tenant_id=7, class_id=2, grade_id=2, gender='male', name='另一年级学生'))
    session.add(CourseHourPlan(tenant_id=7, class_id=2, subject_id=1, academic_year='2026-2027', term='1', weekly_periods=4))
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1, 2], 'start_date': '2026-06-09',
        'rooms': [{'name': 'D', 'capacity': 4}, {'name': 'A', 'capacity': 2}],
        'rules': {'same_subject_same_time': True}})
    assert response.status_code == 200, response.text
    schedules = response.json()['data']['schedules']
    assert len(schedules) == 2
    assert len({(s['exam_date'], s['start_time']) for s in schedules}) == 1
    assert request('GET', '/plans/3/checks').json()['data']['ok']


def test_own_subject_rule_applies_to_generation_and_manual_adjustment(exam_api):
    request, session = exam_api
    session.add(TeachingAssignment(tenant_id=7, class_id=1, subject_id=1, teacher_id=1,
                academic_year='2026-2027', term='1'))
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-06-09',
        'rooms': [{'name': 'D', 'capacity': 4}], 'rules': {'avoid_own_subject': True}})
    assert response.status_code == 200, response.text
    room = response.json()['data']['rooms'][0]
    assert 1 not in room['invigilator_ids']
    adjustment = request('PATCH', f"/plans/3/rooms/{room['id']}", json={'invigilator_ids': [1]})
    assert adjustment.status_code == 409
    assert '回避' in adjustment.json()['detail']


def test_cross_exam_candidate_conflict_moves_to_next_available_session(exam_api):
    request, _ = exam_api
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1], 'start_date': '2026-06-08'})
    assert response.status_code == 200, response.text
    rows = response.json()['data']['schedules']
    assert rows[0]['exam_date'] == '2026-06-08'
    assert rows[0]['start_time'] == '14:30'
    assert request('GET', '/plans/3/checks').json()['data']['ok']


def test_sunday_start_excluded_dates_and_occupied_morning_share_one_calendar(exam_api):
    request, session = exam_api
    body = {'exam_id': 3, 'grade_ids': [1], 'subject_ids': [1],
        'start_date': '2026-06-07', 'excluded_dates': ['2026-06-09'],
        'sessions': [{'start_time': '09:00', 'end_time': '11:00'}, {'start_time': '14:30', 'end_time': '16:30'}],
        'rooms': [{'name': 'D', 'capacity': 4}], 'rules': {'subject_time_slots': {'1': '09:00'}}}
    assert request('PUT', '/exams/3/config', json=body).status_code == 200
    before = session.get(ExamCandidateAssignment, 1).exam_date
    preview = request('GET', '/plans/3/preview')
    assert preview.status_code == 200, preview.text
    calendar = preview.json()['data']
    assert [(r['exam_date'], r['start_time']) for r in calendar] == [('2026-06-10', '09:00')]
    checked = request('POST', '/plans/check', json=body)
    assert checked.status_code == 200, checked.text
    assert session.get(ExamCandidateAssignment, 1).exam_date == before
    generated = request('POST', '/plans', json=body)
    assert generated.status_code == 200, generated.text
    assert [(r['exam_date'], r['start_time']) for r in generated.json()['data']['schedules']] == [('2026-06-10', '09:00')]
    # Its own generated seats cannot force another postponement on regeneration.
    again = request('POST', '/plans', json=body)
    assert again.status_code == 200, again.text
    assert again.json()['data']['schedules'][0]['exam_date'] == '2026-06-10'


def test_overview_includes_other_exam_and_excludes_other_school(exam_api):
    request, session = exam_api
    session.add(ExamSchedule(id=99, tenant_id=99, exam_id=99, grade_id=1, subject_id=1,
        exam_date=date(2026, 6, 8), start_time='09:00', end_time='11:00'))
    session.commit()
    response = request('GET', '/plans/1/overview')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert {s['exam_id'] for s in data['schedules']} == {1, 2}
    assert {r['exam_id'] for r in data['rooms']} == {1, 2}
    assert data['rules']['teacher_daily_limit'] == 4
    assert request('GET', '/plans/99/overview').status_code == 404


def test_overview_can_preview_calendar_before_generation(exam_api):
    request, _ = exam_api
    response = request('GET', '/plans/3/overview')
    assert response.status_code == 200
    assert response.json()['data']['schedules'] == []
    request('PUT', '/exams/3/config', json={'grade_ids': [1], 'start_date': '2026-06-09',
        'sessions': [{'start_time': '09:00', 'end_time': '11:00'}]})
    data = request('GET', '/plans/3/overview').json()['data']
    assert len(data['schedules']) == 1 and data['schedules'][0]['preview']
    assert data['rooms'] == []

def test_own_subject_rule_reports_missing_teaching_data(exam_api):
    request, _ = exam_api
    response = request('POST', '/plans/check', json={'exam_id': 3, 'grade_ids': [1],
        'start_date': '2026-06-09', 'rules': {'avoid_own_subject': True}})
    assert response.status_code == 422
    assert '任教关系未配置' in response.json()['detail']


def test_manual_adjustment_and_report_enforce_cross_exam_daily_limit(exam_api):
    request, session = exam_api
    cfg = session.execute(select(ExamSchedulingConfig).where(ExamSchedulingConfig.exam_id == 1)).scalars().one()
    cfg.rules = {'teacher_daily_limit': 1}
    session.add(ExamSchedule(id=4, tenant_id=7, exam_id=2, grade_id=1, subject_id=1,
        exam_date=date(2026, 6, 8), session_index=10, start_time='14:00', end_time='16:00'))
    session.add(ExamRoomAssignment(id=4, tenant_id=7, exam_id=2, exam_schedule_id=4,
        grade_id=1, subject_id=1, exam_date=date(2026, 6, 8), session_index=10,
        room_name='D', capacity=4, candidate_count=0, invigilator_ids=[1]))
    session.commit()
    response = request('PATCH', '/plans/1/rooms/1', json={'invigilator_ids': [1]})
    assert response.status_code == 409
    assert '含其他考试' in response.json()['detail']
    issues = request('GET', '/plans/1/checks').json()['data']['issues']
    assert any(i['code'] == 'teacher_daily_limit' for i in issues)


def test_exam_catalog_uses_real_school_spaces_and_live_capacity(exam_api):
    request, session = exam_api
    session.add_all([
        Campus(id=1, tenant_id=7, name='高中部'),
        Building(id=1, tenant_id=7, campus_id=1, name='教学楼'),
        Room(id=101, tenant_id=7, building_id=1, name='高二101', capacity=56),
        Room(id=102, tenant_id=7, building_id=1, name='高三102', capacity=60, status='maintenance'),
        Room(id=103, tenant_id=7, building_id=1, name='办公室', capacity=10, room_type='office'),
        Room(id=104, tenant_id=7, building_id=1, name='会议室', capacity=80,
             room_type='meeting', is_exam_enabled=True),
        Room(id=105, tenant_id=99, building_id=1, name='其他学校教室', capacity=100),
    ])
    session.commit()
    response = request('GET', '/rooms?page_size=300')
    assert response.status_code == 200, response.text
    rows = {r['name']: r for r in response.json()['data']['items']}
    assert set(rows) == {'高二101', '高三102', '会议室'}
    assert rows['高二101']['capacity'] == 56
    assert rows['高三102']['status'] == 'maintenance'
    assert rows['高二101']['building'] == '教学楼'
    session.get(Room, 101).capacity = 64
    session.commit()
    response = request('GET', '/rooms?page_size=300')
    assert next(r for r in response.json()['data']['items'] if r['id'] == 101)['capacity'] == 64
    assert request('PUT', '/exams/3/venues', json={'rooms': [{'name': '高三102', 'capacity': 60}]}).status_code == 422
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1],
        'start_date': '2026-06-09'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['rooms'][0]['capacity'] == 64
    assert response.json()['data']['rooms'][0]['room_name'] == '高二101'
    session.get(Room, 101).status = 'disabled'
    session.commit()
    response = request('GET', '/plans/3/checks')
    assert any(i['code'] == 'room_unavailable' for i in response.json()['data']['issues'])


def test_room_catalog_disambiguates_same_names_across_buildings(exam_api):
    request, session = exam_api
    session.add_all([
        Campus(id=1, tenant_id=7, name='高中部'),
        Building(id=1, tenant_id=7, campus_id=1, name='东楼'),
        Building(id=2, tenant_id=7, campus_id=1, name='西楼'),
        Room(id=101, tenant_id=7, building_id=1, name='101', capacity=50),
        Room(id=102, tenant_id=7, building_id=2, name='101', capacity=60),
    ])
    session.commit()
    rows = request('GET', '/rooms?page_size=300').json()['data']['items']
    assert len({r['name'] for r in rows}) == 2
    assert sum(r['capacity'] for r in rows) == 110


def test_whole_grade_exam_does_not_schedule_physics_history_together(exam_api):
    request, session = exam_api
    session.get(Tenant, 7).gaokao_mode = '3+1+2'
    session.add_all([
        Subject(id=2, tenant_id=7, name='物理'),
        Subject(id=3, tenant_id=7, name='历史'),
        CourseHourPlan(tenant_id=7, class_id=1, subject_id=2, academic_year='2026-2027', term='1', weekly_periods=3),
        CourseHourPlan(tenant_id=7, class_id=1, subject_id=3, academic_year='2026-2027', term='1', weekly_periods=3),
    ])
    session.commit()
    response = request('POST', '/plans', json={'exam_id': 3, 'grade_ids': [1],
        'subject_ids': [2, 3], 'candidate_mode': 'grade', 'schedule_mode': 'school',
        'start_date': '2026-06-09', 'rooms': [{'name': 'D', 'capacity': 4}]})
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['summary']['candidate_assignment_count'] == 6
    assert len({(s['exam_date'], s['start_time']) for s in data['schedules']}) == 2
    assert request('GET', '/plans/3/checks').json()['data']['ok']


def test_choice_rotation_finishes_together_and_prints_each_subject_once(exam_api):
    request, session = exam_api
    session.get(Tenant, 7).gaokao_mode = '3+1+2'
    names = {2: '物理', 3: '历史', 4: '语文', 5: '英语', 6: '化学', 7: '地理', 8: '政治', 9: '生物'}
    for subject, name in names.items():
        session.add(Subject(id=subject, tenant_id=7, name=name))
        session.add(CourseHourPlan(tenant_id=7, class_id=1, subject_id=subject,
            academic_year='2026-2027', term='1', weekly_periods=3))
    for sid, primary, pair in [(1, 2, [6, 7]), (2, 3, [7, 8]), (3, 2, [6, 8])]:
        session.add(StudentSubjectChoice(tenant_id=7, student_id=sid, scheme_id=1,
            academic_year='2026-2027', primary_subject_id=primary, secondary_subject_ids=pair))
    session.commit()
    body = {'exam_id': 3, 'grade_ids': [1], 'subject_ids': list(range(1, 10)),
        'candidate_mode': 'choices', 'schedule_mode': 'school', 'start_date': '2026-06-09',
        'rooms': [{'name': 'A', 'capacity': 2}, {'name': 'B', 'capacity': 2}, {'name': 'D', 'capacity': 4}]}
    blocked = request('POST', '/plans/check', json=body)
    assert blocked.status_code == 422
    assert '允许同科目分批' in blocked.text
    body['rules'] = {'allow_subject_batches': True}
    preview = request('POST', '/plans/check', json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['data']['student_count'] == 3
    generated = request('POST', '/plans', json=body)
    assert generated.status_code == 200, generated.text
    assert generated.json()['data']['summary']['candidate_assignment_count'] == 18
    checked = request('GET', '/plans/3/checks').json()['data']
    assert checked['ok'], checked
    printed = request('GET', '/plans/3/admission-tickets')
    assert printed.status_code == 200, printed.text
    tickets = printed.json()['data']['items']
    waves = []
    for ticket in tickets:
        rows = ticket['sessions']
        assert len(rows) == 6
        assert len({r['subject_name'] for r in rows}) == 6
        waves.append([(r['exam_date'], r['start_time'], r['end_time']) for r in rows])
    assert waves[0] == waves[1] == waves[2]
    assert tickets[0]['sessions'][3]['subject_name'] == '物理'
    assert tickets[1]['sessions'][3]['subject_name'] == '历史'


def test_rotation_without_batches_keeps_each_subject_in_one_wave():
    from app.services.exam_rotation import build_rotation
    names = {1: '语文', 2: '数学', 3: '英语', 4: '物理', 5: '历史',
             6: '化学', 7: '地理', 8: '政治', 9: '生物'}
    courses = [{'id': sid, 'grade_id': 1, 'subject_id': sid} for sid in names]
    rosters = {1: [1, 2], 2: [1, 2], 3: [1, 2], 4: [1], 5: [2],
               6: [1], 7: [1, 2], 8: [2], 9: []}
    schedules, _, assigned, batches = build_rotation(courses, rosters, names,
        start_date=date(2026, 6, 9), sessions=(('09:00', '11:00'), ('14:00', '16:00')),
        excluded_dates=set(), room='考场')
    assert not batches
    per_student = {sid: [(s.exam_date, s.start_time, s.end_time) for s in schedules
                        if sid in assigned[s.course_key]] for sid in [1, 2]}
    assert len(per_student[1]) == 6
    assert per_student[1] == per_student[2]
    for subject in names:
        assert len([s for s in schedules if s.subject_id == subject]) <= 1

@pytest.mark.parametrize('start', ['09:00', '14:30'])
def test_subject_time_slot_saved_previewed_and_generated(exam_api, start):
    request, session = exam_api
    session.add_all([Subject(id=2, tenant_id=7, name='语文'), CourseHourPlan(tenant_id=7, class_id=1, subject_id=2, academic_year='2026-2027', term='1', weekly_periods=5)])
    session.commit()
    config = {'grade_ids': [1], 'subject_ids': [2, 1], 'candidate_mode': 'grade', 'schedule_mode': 'custom', 'start_date': '2026-06-10', 'sessions': [{'start_time': '09:00', 'end_time': '11:00'}, {'start_time': '14:30', 'end_time': '16:30'}], 'rules': {'subject_time_slots': {'2': start}, 'student_daily_limit': 1}}
    saved = request('PUT', '/exams/3/config', json=config)
    assert saved.status_code == 200, saved.text
    assert request('GET', '/exams/3/config').json()['data']['rules']['subject_time_slots'] == {'2': start}
    preview = request('GET', '/plans/3/preview')
    assert preview.status_code == 200, preview.text
    assert next(r for r in preview.json()['data'] if r['subject_id'] == 2)['start_time'] == start
    generated = request('POST', '/plans', json={**config, 'exam_id': 3, 'rooms': [{'name': 'D', 'capacity': 4}]})
    assert generated.status_code == 200, generated.text
    rows = generated.json()['data']['schedules']
    assert next(r for r in rows if r['subject_id'] == 2)['start_time'] == start
    assert len({r['exam_date'] for r in rows}) == 2
    assert request('GET', '/plans/3/checks').json()['data']['ok']
    invalid = {**config, 'rules': {'subject_time_slots': {'2': '08:00'}}}
    assert request('PUT', '/exams/3/config', json=invalid).status_code == 422
    assert request('GET', '/exams/3/config').json()['data']['rules']['subject_time_slots'] == {'2': start}


def test_new_exam_defaults_to_whole_grade_and_preserves_explicit_choices(exam_api):
    request, _ = exam_api
    initial = request('GET', '/exams/3/config')
    assert initial.status_code == 200
    assert initial.json()['data']['candidate_mode'] == 'grade'
    response = request('PUT', '/exams/3/config', json={'grade_ids': [1], 'candidate_mode': 'choices', 'sessions': [{'start_time':'09:00','end_time':'11:00'}]})
    assert response.status_code == 200, response.text
    assert request('GET', '/exams/3/config').json()['data']['candidate_mode'] == 'choices'


@pytest.mark.parametrize('scopes,current_term,expected_mode,source', [
    ({'2026-2027:1': 'administrative'}, '2', 'grade', 'school_term_setting'),
    ({}, '2', 'grade', 'unverified_historical'),
    ({}, '1', 'choices', 'school_current_setting'),
])
def test_exam_uses_its_semester_environment(exam_api, scopes, current_term, expected_mode, source):
    request, session = exam_api
    session.add_all([
        TenantConfig(tenant_id=7, config_key='academic_years', config_value={
            'current_academic_year': '2026-2027', 'current_term': current_term}),
        TenantConfig(tenant_id=7, config_key='timetable_mode', config_value={
            'mode': 'walk_class', 'scopes': scopes}),
        TenantConfig(tenant_id=99, config_key='timetable_mode', config_value={
            'mode': 'walk_class', 'scopes': {'2026-2027:1': 'walk_class'}}),
    ])
    session.commit()
    data = request('GET', '/exams/3/config').json()['data']
    assert data['candidate_mode'] == expected_mode
    assert data['environment']['source'] == source
    assert data['rules']['reference_mode'] == 'auto'
    # Explicit special-exam choice remains effective even with an administrative semester.
    saved = request('PUT', '/exams/3/config', json={'grade_ids': [1],
        'candidate_mode': 'choices', 'rules': {'reference_mode': 'manual'}})
    assert saved.status_code == 200, saved.text
    assert request('GET', '/exams/3/config').json()['data']['candidate_mode'] == 'choices'


def test_auto_environment_is_applied_to_preview_and_generation(exam_api):
    request, session = exam_api
    session.add(TenantConfig(tenant_id=7, config_key='timetable_mode', config_value={
        'mode': 'walk_class', 'scopes': {'2026-2027:1': 'administrative'}}))
    session.commit()
    body = {'exam_id': 3, 'grade_ids': [1], 'candidate_mode': 'choices',
        'start_date': '2026-06-11', 'rules': {'reference_mode': 'auto'},
        'rooms': [{'name': 'D', 'capacity': 4}]}
    assert request('PUT', '/exams/3/config', json=body).status_code == 200
    preview = request('GET', '/plans/3/preview')
    assert preview.status_code == 200, preview.text
    generated = request('POST', '/plans', json=body)
    assert generated.status_code == 200, generated.text
    assert generated.json()['data']['summary']['candidate_assignment_count'] == 3


def test_repeated_saves_and_generation_replace_same_exam_only(exam_api):
    request, session = exam_api
    config = {'grade_ids': [1], 'subject_ids': [1], 'candidate_mode': 'grade',
        'start_date': '2026-06-11', 'rules': {'reference_mode': 'auto'},
        'sessions': [{'start_time': '09:00', 'end_time': '11:00'}]}
    for day in ('2026-06-10', '2026-06-11'):
        response = request('PUT', '/exams/3/config', json={**config, 'start_date': day})
        assert response.status_code == 200, response.text
        response = request('PUT', '/exams/3/venues', json={'rooms': [{'name': 'D', 'capacity': 4}]})
        assert response.status_code == 200, response.text
    assert len(session.execute(select(ExamSchedulingConfig).where(ExamSchedulingConfig.exam_id == 3)).scalars().all()) == 1
    assert len(session.execute(select(ExamVenue).where(ExamVenue.exam_id == 3)).scalars().all()) == 1
    for day in ('2026-06-11', '2026-06-12'):
        generated = request('POST', '/plans', json={**config, 'exam_id': 3, 'start_date': day,
            'rooms': [{'name': 'D', 'capacity': 4}]})
        assert generated.status_code == 200, generated.text
        for model, count in ((ExamSchedule, 1), (ExamRoomAssignment, 1), (ExamCandidateAssignment, 3)):
            rows = session.execute(select(model).where(model.exam_id == 3)).scalars().all()
            assert len(rows) == count
            assert all(r.exam_date.isoformat() == day for r in rows)
    assert len(session.execute(select(ExamCandidateAssignment).where(ExamCandidateAssignment.exam_id == 1)).scalars().all()) == 3
    assert session.get(ExamRoomAssignment, 3).exam_id == 2


def test_switching_semesters_preserves_mode_without_extra_teacher_configuration(exam_api):
    from types import SimpleNamespace
    from app.api.v1.auth import AcademicYearsIn, SchoolSettingsIn, save_academic_years, update_school_settings
    from app.models.org import BaseUserRole
    _, session = exam_api
    session.add_all([
        TenantConfig(tenant_id=7, config_key='academic_years', config_value={
            'current_entry_year': 2026, 'current_academic_year': '2026-2027', 'current_term': '1'}),
        TenantConfig(tenant_id=7, config_key='timetable_mode', config_value={'mode': 'administrative'}),
    ])
    session.commit()
    class Adapter:
        async def execute(self, statement): return session.execute(statement)
        async def get(self, model, key): return session.get(model, key)
        def add(self, row): session.add(row)
        async def commit(self): session.commit()
        async def refresh(self, row): session.refresh(row)
    user = SimpleNamespace(id=1, tenant_id=7, role=BaseUserRole.director)
    adapter = Adapter()
    async def run():
        await save_academic_years(AcademicYearsIn(years=[{'entry_year': 2026}],
            current_entry_year=2026, current_term='2'), user=user, session=adapter)
        await update_school_settings(SchoolSettingsIn(timetable_mode='walk_class'), user=user, session=adapter)
        await save_academic_years(AcademicYearsIn(years=[{'entry_year': 2026}],
            current_entry_year=2026, current_term='1'), user=user, session=adapter)
    asyncio.run(run())
    data = session.execute(select(TenantConfig).where(TenantConfig.config_key == 'timetable_mode')).scalar_one().config_value
    assert data['scopes'] == {'2026-2027:1': 'administrative', '2026-2027:2': 'walk_class'}
    assert data['mode'] == 'administrative'
