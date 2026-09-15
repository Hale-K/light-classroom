from app.ai.supervisor import (
    SupervisorKind,
    SupervisorReport,
    SupervisorResult,
    SupervisorResultStatus,
    SupervisorTask,
)


def test_supervisor_contract_keeps_readiness_result_separate_from_summary():
    task = SupervisorTask(
        id="schedule_setup",
        label="学期与课位",
        instruction="检查当前学期和课位结构",
        allowed_tools=frozenset({"lookup_schedule_setup"}),
    )
    result = SupervisorResult(
        task_id=task.id,
        status=SupervisorResultStatus.SUCCEEDED,
        facts=("课位结构已保存",),
        missing=("无",),
        next_steps=("继续检查课时",),
    )
    report = SupervisorReport(
        kind=SupervisorKind.READINESS,
        results=(result,),
        summary="排课准备检查完成",
    )

    assert report.kind is SupervisorKind.READINESS
    assert report.results[0].facts == ("课位结构已保存",)
    assert report.failed_tasks == ()


def test_supervisor_report_exposes_failed_task_ids():
    report = SupervisorReport(
        kind=SupervisorKind.DIAGNOSIS,
        results=(
            SupervisorResult("status", SupervisorResultStatus.FAILED, error="读取失败"),
            SupervisorResult("rules", SupervisorResultStatus.SUCCEEDED),
        ),
    )

    assert report.failed_tasks == ("status",)
