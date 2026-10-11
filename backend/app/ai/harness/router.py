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
        "排考用lookup_exam_operations：先明确考试，查询参考模式grade/choices、日程custom/school和考场规则，不用行政班/走班课表模式代替排考环境。"
        "排考可核对考试配置、日程、考场、监考工作量、考生座位和checks冲突；缺考试或配置时给待确认计划并集中追问。"
        "同场考场与监考需求用calculate_exam_capacity验算：参考人数、规则后可用座位、每间监考人数均须有依据；不能用班额替代考试座位。"
        "排考建议需区分去重人数、考生场次、物理考场和考场场次，检查结果按总量与has_more翻页。当前工具只读，不能声称已生成、调整、保存或打印排考。"
        "面向用户将参考和日程模式翻译为中文业务含义，不显示grade、choices、custom、school、total等内部字段。"
        "回答必须适配已核实的模式、年级和学期；当前页面不是用户指定范围，不据此猜测年级或将历史模式当当前模式。"
        "关键决策缺失时调用request_clarification展示引导卡并等待，不只输出笼统反问。保留用户明确的约束，只问会改变结果的缺项，最多四题；可查询的学校模式、学年和学期先自动核对。用户补充后沿用先前条件，不能当成新任务。"
        "问题目标、对象或关键约束不清楚时，先给简短待确认计划，列明已知信息、待补充项与下一步，集中提出关键问题。"
        "复杂模式用plan_task记录计划，将依赖缺失信息的步骤标blocked并等待用户；明确说明未执行，不把缺项步骤标完成。"
        "不得为消除歧义自行选年级、课时或教师工作量；若可以给示例，必须明确为待确认假设且不能宣称正式方案完成。"
        "不要创建规则草稿。"
    ),
    allowed_tools=frozenset({
        "format_markdown", "request_clarification",
        'lookup_school_context',
        'lookup_room_resources',
        'calculate_resource_plan',
        'lookup_exam_operations',
        'calculate_exam_capacity',
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
        '用户只要求核对现有配置时，仅查询已保存数据并对比用户约束，不额外设计候选方案；历史测算不等于已保存课时，缺少配置如实报告。'
        '多方案课时规划先lookup_planning_basis核对该年级学期实际课位及单双周；'
        '生成最多三案后调用validate_hour_scenarios验算合计、必排容量及固定科目。校验不通过先修正再交付。'
        '用户已说明周一至周六与必排/可选课位时直接沿用，不再追问课位；验算weekdays须包含6。'
        '设计课时方案必须交付单周、双周各科周一至周五课时、周六课时及全周合计，周六不可只混在全周总数中。'
        '按validate_hour_scenarios返回daily_distribution_by_week列示分配草案及每天合计，说明已核对必排和可选容量，未验证教师、教室或完整排课可行性。'
        '排版每表最多5列：单周、双周各用科目/周一至周五/周六/全周课时四列表；每日合计按星期逐行列单周、双周，不铺成七列。'
        '全部查询按has_more翻页；不要把前几条当全部。'
        '高考分值未配置时说明缺失；可先按明确标注的教育均衡假设提出建议，不能假称比例已核实。'
        '用户提供人数和班额问需要几个班、教室和教师，是需求规划。用calculate_resource_plan计算，不用现有空间数量代替需求。'
        '教师数依赖各科周课时和教师周授课量。未给定时明确列出待确认的示例假设再算；心理、音乐、美术、体育分别列行。'
        '多轮修改师资仍须calculate_resource_plan重新验算，不能仅心算。隔周课填开课周实际课时及week_parity，按单双周峰值核对教师，不能按平均0.5节推定1人能覆盖单周20节。'
        '需求估算无需分页读取全校教师名单；只有用户要求比较现有资源或缺口时才查库存。单次计算后直接交付班额表和学科师资表，不重复取证。'
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
