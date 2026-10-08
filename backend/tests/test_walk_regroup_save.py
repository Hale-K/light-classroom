import pytest
from app.services.scheduling.walk_regroup_save import partition_candidates, fingerprint
from app.services.scheduling.rules import RuleDefinition, RuleTarget, RuleGroupDocument


def test_partitions_cover_arbitrary_admin_ids_and_respect_capacity():
    counts = {i: 40 for i in range(101, 111)}
    a, b, excluded = next(partition_candidates(counts, [25, 28, 31, 33], 45))
    assert set(a) == set(b) == set(counts)
    assert set(excluded) == set(b.values())
    assert all(sum(counts[c] for c in b if b[c] == g) <= 135 for g in excluded)


def test_regroup_keeps_configured_teacher_by_subject_class_sequence():
    from types import SimpleNamespace
    from app.services.scheduling.walk_regroup_save import fixed_walk_class_mapping, fixed_walk_teacher_mapping
    existing = [
        SimpleNamespace(id=1001, subject_id=10, sequence=1, teacher_id=501, name='政治走班01'),
        SimpleNamespace(id=1002, subject_id=10, sequence=2, teacher_id=502, name='政治走班02'),
    ]
    generated = [
        {'id': 21, 'subject_id': 10},
        {'id': 22, 'subject_id': 10},
    ]
    assert fixed_walk_teacher_mapping(existing, generated) == {21: 501, 22: 502}
    assert fixed_walk_class_mapping(existing, generated) == (
        {21: 501, 22: 502}, {21: 1001, 22: 1002},
    )


def test_regroup_refuses_to_silently_change_teacher_assignment_count():
    from types import SimpleNamespace
    from app.services.scheduling.walk_regroup_save import fixed_walk_teacher_mapping
    existing = [SimpleNamespace(id=1001, subject_id=10, sequence=1, teacher_id=501, name='政治走班01')]
    generated = [{'id': 21, 'subject_id': 10}, {'id': 22, 'subject_id': 10}]
    with pytest.raises(ValueError, match='为避免擅自调整老师'):
        fixed_walk_teacher_mapping(existing, generated)


def test_balanced_rosters_keep_the_selected_existing_class_identity_and_teacher():
    from types import SimpleNamespace
    from app.services.scheduling.walk_regroup_save import fixed_walk_class_mapping
    existing = [SimpleNamespace(id=1001, subject_id=10, sequence=1, teacher_id=501, name='政治01'),
                SimpleNamespace(id=1002, subject_id=10, sequence=2, teacher_id=502, name='政治02')]
    generated = [{'id': 1, 'subject_id': 10, 'configured_class_id': 1002},
                 {'id': 2, 'subject_id': 10, 'configured_class_id': 1001}]
    assert fixed_walk_class_mapping(existing, generated) == ({1: 502, 2: 501}, {1: 1002, 2: 1001})
    generated[1]['configured_class_id'] = 1002
    with pytest.raises(ValueError, match='对应关系不完整'):
        fixed_walk_class_mapping(existing, generated)


def test_fingerprint_detects_changes_and_is_order_independent():
    assert fingerprint({'a': 1, 'b': [2]}) == fingerprint({'b': [2], 'a': 1})
    assert fingerprint({'a': 1}) != fingerprint({'a': 2})


def test_joint_scheduling_keeps_user_rules_without_generating_coordination_rules():
    from app.services.scheduling.walk_regroup_save import user_rule_group
    group = RuleGroupDocument(id='g', name='rules', academic_year='2026-2027', term='2', grade_id=12,
        rules=[RuleDefinition(id='student-gap-minimize', title='old', code='class_gap_free',
            schedule_scope='admin', priority='hard', target=RuleTarget(type='global'))])
    original = group.model_dump()
    assert user_rule_group(group).model_dump() == original
    assert group.model_dump() == original


def test_unreviewed_enabled_rules_fail_closed():
    from app.services.scheduling.walk_regroup_save import check_supported_user_rules
    group = RuleGroupDocument(id='g', name='rules', academic_year='2026-2027', term='2', grade_id=12,
        rules=[RuleDefinition(id='custom', title='custom', code='teacher_daily_limit',
            priority='hard', target=RuleTarget(type='global'), params={'max_per_day': 1})])
    with pytest.raises(ValueError, match='custom'):
        check_supported_user_rules(group)


def test_cleanup_removes_only_known_generated_rules_in_requested_scope():
    from app.services.scheduling.walk_regroup_save import clean_generated_rule_catalog
    value = {'2026-2027:2': {'id': 'g', 'grade_id': 12, 'active_id': 'g',
        'rules': [{'id': 'regroup-reserve-101-1'}], 'groups': [
        {'id': 'g', 'grade_id': 12, 'rules': [
            {'id': 'R01'}, {'id': 'regroup-reserve-101-1'},
            {'id': 'regroup-daytime-range'}, {'id': 'regroup-student-contiguous'},
            {'id': 'regroup-custom'}, {'id': 'student-gap-minimize', 'enabled': False}]},
        {'id': 'other', 'grade_id': 13, 'rules': [{'id': 'regroup-reserve-201-1'}]}]},
        '2026-2027:1': {'groups': [{'id': 'g', 'grade_id': 12,
                                  'rules': [{'id': 'regroup-reserve-101-1'}]}]}}
    original = fingerprint(value)
    cleaned, count = clean_generated_rule_catalog(value, '2026-2027', '2', 12)
    assert count == 3
    assert [r['id'] for r in cleaned['2026-2027:2']['groups'][0]['rules']] == [
        'R01', 'regroup-custom', 'student-gap-minimize']
    assert cleaned['2026-2027:2']['groups'][1] == value['2026-2027:2']['groups'][1]
    assert cleaned['2026-2027:1'] == value['2026-2027:1']
    assert cleaned['2026-2027:2']['rules'] == cleaned['2026-2027:2']['groups'][0]['rules']
    assert fingerprint(value) == original


@pytest.mark.parametrize('change', ['token', 'scope', 'stale', 'expired'])
def test_save_rejects_invalid_preview_without_mutation(change):
    from app.services.scheduling.walk_regroup_save import validate_preview
    from fastapi import HTTPException
    cached = {'token': 't', 'scope': [12, '2026-2027', '2'], 'fingerprint': 'f', 'expires_at': 1000}
    args = ['t', [12, '2026-2027', '2'], 'f', 900]
    if change == 'token': args[0] = 'wrong'
    if change == 'scope': args[1] = [12, '2026-2027', '1']
    if change == 'stale': args[2] = 'changed'
    if change == 'expired': args[3] = 1001
    with pytest.raises(HTTPException) as error:
        validate_preview(cached, *args)
    assert error.value.status_code == 409
    assert cached['token'] == 't'


def test_save_input_requires_explicit_replacement_confirmation():
    from app.api.v1.gaokao import WalkRegroupSaveIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WalkRegroupSaveIn(grade_id=12, academic_year='2026-2027', term='2', preview_token='t')


def test_joint_preview_defaults_to_five_student_capacity_overflow():
    from app.api.v1.gaokao import WalkRegroupAutoIn
    body = WalkRegroupAutoIn(grade_id=12, academic_year='2026-2027', term='2')
    assert body.capacity == 45
    assert body.capacity_overflow == 5


@pytest.mark.asyncio
async def test_atomic_replacement_preserves_upper_term_other_tenant_and_students(monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlmodel import SQLModel
    from app.models.org import Grade, Subject, Class, Student, Schedule, TenantConfig
    from app.models.facility import Room
    from app.models.gaokao import (TeachingClass, TeachingClassStudent, TeachingClassSchedule,
        TeachingSubjectHourPlan, WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom)
    from app.api.v1.gaokao import WalkRegroupSaveIn
    from app.api.v1 import scheduling
    from app.services.scheduling.walk_regroup_save import persist_candidate
    models = [Grade, Subject, Class, Student, Schedule, TenantConfig, Room, TeachingClass,
        TeachingClassStudent, TeachingClassSchedule, TeachingSubjectHourPlan,
        WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom]
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine) as db:
        db.add_all([Grade(id=12, tenant_id=7, name='高一', level=1), Subject(id=25, name='地理'),
            Class(id=101, tenant_id=7, grade_id=12, name='一班', term='2'),
            Student(id=1, tenant_id=7, name='学生', gender='male', class_id=101),
            Room(id=1, tenant_id=7, building_id=9, name='教室11'),
            TeachingSubjectHourPlan(id=1, tenant_id=7, grade_id=12, subject_id=25,
                academic_year='2026-2027', term='2', weekly_periods=4)])
        for cid, term, tenant in [(1, '2', 7), (2, '1', 7), (3, '2', 8)]:
            db.add(TeachingClass(id=cid, tenant_id=tenant, grade_id=12, subject_id=25,
                sequence=1, name=f'旧班{cid}', academic_year='2026-2027', term=term,
                teacher_id=500 if cid == 1 else None, capacity=45))
            db.add(TeachingClassStudent(tenant_id=tenant, teaching_class_id=cid, student_id=1))
            db.add(TeachingClassSchedule(tenant_id=tenant, teaching_class_id=cid, subject_id=25,
                academic_year='2026-2027', term=term, weekday=1, period=1))
            db.add(Schedule(tenant_id=tenant, class_id=101, subject_id=25, academic_year='2026-2027',
                term=term, weekday=1, period=1))
        db.commit()
        catalog = {'2026-2027:2': {'groups': [{'id': 'g', 'rules': [{'id': 'R01'}]}]}}
        db.add(TenantConfig(tenant_id=7, config_key='scheduling_rule_group', config_value=catalog))
        db.commit()
        class Adapter:
            async def execute(self, stmt): return db.execute(stmt)
            async def get(self, model, key): return db.get(model, key)
            def add(self, row): db.add(row)
            def add_all(self, rows): db.add_all(rows)
            async def flush(self): db.flush()
        group = RuleGroupDocument(id='g', name='rules', grade_id=12, academic_year='2026-2027', term='2')
        async def load(*args): return [group], 'g'
        monkeypatch.setattr(scheduling, '_load_rule_catalog', load)
        body = WalkRegroupSaveIn(grade_id=12, academic_year='2026-2027', term='2',
                                preview_token='t', confirm_replace=True)
        candidate = {'a_groups': {101: 0}, 'classes': [{'id': 1, 'subject_id': 25, 'capacity': 50,
                    'size': 1}], 'class_id_map': {'1': 1},
            'members': [[1, 1]], 'calendar': {'teachers': {'1': 500}, 'public': [
                {'class_id': 101, 'subject_id': 25, 'teacher_id': 500, 'weekday': 1, 'period': 2, 'room': '本班'}]},
            'placements': [{'teaching_class_id': 1, 'subject_id': 25, 'teacher_id': 500,
                'weekday': 1, 'period': 1, 'room_id': 1}], 'rules': group.model_dump(), 'audit': {'student_count': 1}}
        result = await persist_candidate(body, candidate, Adapter(), 7, 100)
        db.commit()
        assert result['saved'] is True
        assert db.get(Student, 1).class_id == 101
        all_classes = db.execute(select(TeachingClass)).scalars().all()
        assert sorted(c.name for c in all_classes) == ['旧班1', '旧班2', '旧班3']
        assert db.get(TeachingClass, 1).teacher_id == 500
        assert db.get(TeachingClass, 1).capacity == 50
        memberships = db.execute(select(TeachingClassStudent).where(
            TeachingClassStudent.tenant_id == 7,
            TeachingClassStudent.teaching_class_id == 1)).scalars().all()
        assert [row.student_id for row in memberships] == [1]
        saved_walk = db.execute(select(TeachingClassSchedule).where(
            TeachingClassSchedule.tenant_id == 7,
            TeachingClassSchedule.teaching_class_id == 1)).scalars().all()
        assert len(saved_walk) == 1 and saved_walk[0].teaching_class_id == 1
        assert sorted((r.tenant_id, r.term, r.period) for r in db.execute(select(Schedule)).scalars()) == [
            (7, '1', 1), (7, '2', 2), (8, '2', 1)]
        keys = [r.config_key for r in db.execute(select(TenantConfig)).scalars()]
        stored = db.execute(select(TenantConfig).where(
            TenantConfig.config_key == 'scheduling_rule_group')).scalar_one()
        assert stored.config_value == catalog
        assert not any('snapshot' in k or 'backup' in k or 'history' in k for k in keys)
        # An exception before commit can restore the complete original transaction state.
        await persist_candidate(body, candidate, Adapter(), 7, 100)
        db.rollback()
        assert sorted(c.name for c in db.execute(select(TeachingClass)).scalars()) == [
            '旧班1', '旧班2', '旧班3']
    engine.dispose()
