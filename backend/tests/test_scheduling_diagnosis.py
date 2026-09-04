from app.services.scheduling.rules import RuleGroupDocument
from app.services.scheduling.diagnosis import (
    apply_suggestion_to_group,
    diagnose_generation_failure,
)


def _group() -> RuleGroupDocument:
    return RuleGroupDocument.model_validate(
        {
            "id": "g1",
            "name": "高一",
            "academic_year": "2026-2027",
            "term": "1",
            "rules": [
                {
                    "id": "R18-s",
                    "title": "第8、9节仅活动课",
                    "code": "class_allowed_subjects",
                    "enabled": True,
                    "priority": "hard",
                    "target": {"type": "class", "ids": list(range(627, 637))},
                    "weekdays": [1, 2, 3, 4, 5],
                    "periods": [8, 9],
                    "params": {"allowed_subject_ids": [19, 23, 24]},
                },
                {
                    "id": "R17-02",
                    "title": "第5节最多2节",
                    "code": "slot_teacher_balance",
                    "enabled": True,
                    "priority": "hard",
                    "target": {"type": "global", "ids": []},
                    "weekdays": [1, 2, 3, 4, 5, 6],
                    "periods": [5],
                    "params": {"max_per_teacher": 2},
                },
            ],
        }
    )


def test_diagnose_marks_daytime_stuck_and_pipeline():
    diagnosis = diagnose_generation_failure(
        failure_kind="cpsat_infeasible",
        message="无解",
        rule_group=_group(),
        solver_status="INFEASIBLE",
    )
    assert diagnosis["stuck_step"] == "daytime_search"
    assert diagnosis["rule_group_id"] == "g1"
    assert any(step["id"] == "daytime_search" for step in diagnosis["pipeline"])
    assert diagnosis["suggestions"]
    assert diagnosis["suggestions"][0]["applicable"] is True


def test_apply_demote_and_relax():
    group = _group()
    demoted, note = apply_suggestion_to_group(
        group,
        {"rule_id": "R18-s", "action": "demote_to_soft"},
    )
    assert "软目标" in note
    assert next(r for r in demoted.rules if r.id == "R18-s").priority == "soft"

    relaxed, _ = apply_suggestion_to_group(
        demoted,
        {
            "rule_id": "R17-02",
            "action": "relax_param",
            "param_patch": {"max_per_teacher": 3},
        },
    )
    assert next(r for r in relaxed.rules if r.id == "R17-02").params["max_per_teacher"] == 3
