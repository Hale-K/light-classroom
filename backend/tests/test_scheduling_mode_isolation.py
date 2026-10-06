from app.api.v1 import scheduling
from app.api.v1.scheduling import GenerateIn


async def test_administrative_validation_does_not_read_gaokao_scheme(monkeypatch):
    assignments = [
        {"id": 1, "class_id": 10, "subject_id": 26, "teacher_id": 101, "weekly_periods": 2},
        {"id": 2, "class_id": 10, "subject_id": 32, "teacher_id": 102, "weekly_periods": 2},
    ]

    async def load_assignments(_session, _body, _tenant_id):
        return assignments

    class NoDatabaseAccess:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("行政班排课校验不应读取选科方案")

    monkeypatch.setattr(scheduling, "_generation_assignment_payloads", load_assignments)
    result = await scheduling.validate_schedule(
        GenerateIn(academic_year="2026-2027", days=6, periods_per_day=9),
        session=NoDatabaseAccess(),
        user=object(),
        tenant_id=7,
    )

    assert result["data"]["valid"] is True
    assert not any(
        issue["code"] == "primary_admin_track_conflict"
        for issue in result["data"]["issues"]
    )
