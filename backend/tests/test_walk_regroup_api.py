import pytest
from pydantic import ValidationError

from app.api.v1.gaokao import WalkRegroupPreviewIn, preview_walk_regroup


def test_regroup_preview_requires_explicit_partition_configuration():
    with pytest.raises(ValidationError):
        WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2')


def test_regroup_preview_rejects_negative_class_id():
    with pytest.raises(ValidationError):
        WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2',
            a_groups={-1: 0}, b_groups={-1: 0}, b_excluded_subject={0: 10})


def test_regroup_preview_has_no_save_flag():
    with pytest.raises(ValidationError):
        WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2',
            a_groups={100: 0}, b_groups={100: 0}, b_excluded_subject={0: 10}, apply=True)


@pytest.mark.asyncio
async def test_regroup_preview_rejects_other_tenant_grade():
    from types import SimpleNamespace
    from fastapi import HTTPException
    class Session:
        async def get(self, model, pk):
            return SimpleNamespace(tenant_id=9)
    body = WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2',
        a_groups={100: 0}, b_groups={100: 0}, b_excluded_subject={0: 10})
    with pytest.raises(HTTPException) as error:
        await preview_walk_regroup(body, Session(), 7)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_regroup_preview_preserves_choices_and_never_commits(monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import gaokao
    from app.models.org import Class
    class Result:
        def __init__(self, rows):
            self.rows = rows
        def scalars(self):
            return iter(self.rows)
        def all(self):
            return self.rows
    class Session:
        def __init__(self):
            self.rows = iter([
                [SimpleNamespace(student_id=1, secondary_subject_ids=[10, 20])],
                [(1, Class(id=100, grade_id=12, name='A', tenant_id=7, academic_year='2026-2027', term='2'))]])
        async def get(self, model, pk):
            return SimpleNamespace(tenant_id=7)
        async def execute(self, query):
            return Result(next(self.rows))
        async def commit(self):
            raise AssertionError('Preview must not commit')
        def add(self, row):
            raise AssertionError('Preview must not mutate')
    async def student_ids(session, tenant_id, grade_id, academic_year):
        return [1]
    async def calendar(*args):
        return {'schedule_validated': True, 'current_rules_validated': False}
    monkeypatch.setattr(gaokao, '_grade_student_ids', student_ids)
    monkeypatch.setattr(gaokao, '_preview_regroup_calendar', calendar)
    body = WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2',
        a_groups={100: 0}, b_groups={100: 0}, b_excluded_subject={0: 10})
    result = (await preview_walk_regroup(body, Session(), 7))['data']
    assert result['saved'] is False
    assert result['schedule_validated'] is True
    assert {c['subject_id'] for c in result['classes']} == {10, 20}
    assert len(result['members']) == 2


@pytest.mark.parametrize('periods', [[2, 3], [1, 3], [1, 1]])
def test_non_contiguous_required_periods_are_rejected(periods):
    with pytest.raises(ValidationError):
        WalkRegroupPreviewIn(grade_id=12, academic_year='2026-2027', term='2',
            a_groups={100: 0}, b_groups={100: 0}, b_excluded_subject={0: 10}, periods=periods)
