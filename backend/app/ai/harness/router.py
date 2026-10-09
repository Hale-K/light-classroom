"""Select a fixed, reviewable harness for an assistant task.

The router deliberately returns registered data only. It never evaluates model-
generated Python or lets a request add tools to its own capability set.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from app.ai.intent import AssistantRoute, ExecutionMode, IntentDecision


@dataclass(frozen=True, slots=True)
class HarnessProfile:
    name: str
    label: str
    strategy: str
    instructions: str
    allowed_tools: frozenset[str]
    max_steps: int
    step_timeout_seconds: int
    turn_timeout_seconds: int
    temperature: float = 0.2

    def trace_data(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "strategy": self.strategy,
            "allowed_tools": sorted(self.allowed_tools),
            "max_steps": self.max_steps,
            "step_timeout_seconds": self.step_timeout_seconds,
            "turn_timeout_seconds": self.turn_timeout_seconds,
        }


class HarnessRouterService(Protocol):
    def select(self, decision: IntentDecision) -> HarnessProfile: ...


QUERY_HARNESS = HarnessProfile(
    name="query",
    label="普通问答/查询",
    strategy="direct_or_react",
    instructions=(
        "先理解用户当前的问题：能直接回答就直接回答，范围不明确先追问，"
        "只有回答依赖本校真实数据时才调用工具。"
        "根据每次工具返回的证据决定是否继续查询，不因问题标签而执行固定检查链。"
        "明确区分事实、推断和未核实项；证据不足时不要声称已完成全面检查。"
        "排课问题按问题选择日志、容量或走班数据工具，不默认检查全校。"
        "走班人数与固定任课用 lookup_walk_classes，缺年级先澄清；禁止凭经验编造根因。"
        "学生选科与入班查 lookup_student_choices；行政和走班任课查 lookup_teaching_assignments；"
        "合并或个人课表查 lookup_timetable；资源碰撞查 lookup_schedule_conflicts。"
        "按查询结果的缺失数据说明校验边界；完整列表按 has_more 继续分页。"
        "学校模式先查 lookup_school_context；行政模式只查行政课，走班模式区分行政课和走班课，两者可合并。"
        "不要创建规则草稿。"
    ),
    allowed_tools=frozenset({
        "format_markdown",
        'lookup_school_context',
        "lookup_playbook", "lookup_schedule_setup", "lookup_teachers", "lookup_rules",
        "lookup_generation_status",
        "lookup_generation_log", "lookup_subject_capacity", "lookup_remaining_capacity",
        "lookup_slot_role_capacity", "lookup_walk_classes",
        "lookup_student_choices", "lookup_teaching_assignments",
        "lookup_timetable", "lookup_schedule_conflicts",
        "lookup_planning_basis", "validate_hour_scenarios",
    }),
    max_steps=4,
    step_timeout_seconds=120,
    turn_timeout_seconds=240,
)

DIRECT_HARNESS = HarnessProfile(
    name="query",
    label="普通问答/查询",
    strategy="direct",
    instructions="直接回答当前问题，不读取学校数据，不调用工具，不创建任何草稿。",
    allowed_tools=frozenset(),
    max_steps=1,
    step_timeout_seconds=30,
    turn_timeout_seconds=45,
)

PLANNING_HARNESS = replace(
    QUERY_HARNESS,
    name='planning', label='复杂规划/执行', strategy='planned_react',
    max_steps=20, step_timeout_seconds=120, turn_timeout_seconds=600,
    allowed_tools=QUERY_HARNESS.allowed_tools | {'plan_task', 'update_plan_task'},
    instructions=(
        '复杂任务先调用plan_task列出简明业务步骤，步骤名不写工具名。完成取证或验算后立即用update_plan_task更新该步骤状态和证据摘要。'
        '同次模型回复可批量调用多个状态更新；交付前补齐早先完成步骤，汇总步骤准备好正式内容后标完成，再单独调用format_markdown。'
        '依次核对环境范围、取得必要证据、形成候选结果、程序校验、完整汇总；按问题调整步骤，不执行无关固定检查。'
        '多方案课时规划先lookup_planning_basis核对该年级学期实际课位及单双周；'
        '生成最多三案后调用validate_hour_scenarios验算合计、必排容量及固定科目。校验不通过先修正再交付。'
        '全部查询按has_more翻页；不要把前几条当全部。'
        '高考分值未配置时说明缺失；可先按明确标注的教育均衡假设提出建议，不能假称比例已核实。'
        '缺数据标blocked并集中询问；不得把未完成或失败步骤标completed。'
        '每次循环最多120秒，整任务600秒；已有证据直接复用，完成即停止。'
        + QUERY_HARNESS.instructions
    ),
)

# Compatibility imports for integrations; interactive routing registers only two profiles.
GUIDE_HARNESS = QUERY_HARNESS
PLAN_HARNESS = replace(PLANNING_HARNESS, instructions=(
    '本轮为只读计划模式：只查询、分析和建议，不创建规则草稿、不修改任何业务数据。'
    + PLANNING_HARNESS.instructions))


def apply_assistant_mode(profile: HarnessProfile, page_context: dict | None) -> HarnessProfile:
    if (page_context or {}).get('assistant_mode') != 'plan':
        return profile
    return replace(profile, allowed_tools=profile.allowed_tools - {'propose_rules'},
        instructions='本轮为只读计划模式：禁止草稿与数据修改。' + profile.instructions)

READINESS_HARNESS = PLANNING_HARNESS
DIAGNOSIS_HARNESS = PLANNING_HARNESS
CONFIGURATION_HARNESS = PLANNING_HARNESS


class HarnessRouter:
    """Map a classified intent to one server-owned harness profile."""

    profiles = MappingProxyType({
        profile.name: profile
        for profile in (
            QUERY_HARNESS, PLANNING_HARNESS,
        )
    })

    def select(self, decision: IntentDecision) -> HarnessProfile:
        if decision.route is AssistantRoute.DIRECT and decision.effective_mode is ExecutionMode.QUERY:
            return DIRECT_HARNESS
        profile = PLANNING_HARNESS if decision.effective_mode is ExecutionMode.PLANNING else QUERY_HARNESS
        if decision.write_requested:
            # This grants only proposal visibility. ToolScope separately checks
            # real authority, and persistence requires the confirmation endpoint.
            return replace(profile, allowed_tools=profile.allowed_tools | {'propose_rules'},
                instructions=profile.instructions.replace('不要创建规则草稿。', '')
                + '用户明确要求配置规则时可生成待确认草稿；实际写入仍需独立确认。')
        return profile
