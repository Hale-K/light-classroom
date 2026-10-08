"""Select a fixed, reviewable harness for an assistant task.

The router deliberately returns registered data only. It never evaluates model-
generated Python or lets a request add tools to its own capability set.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from app.ai.intent import AssistantIntent, AssistantRoute, IntentDecision


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


GUIDE_HARNESS = HarnessProfile(
    name="guide",
    label="页面说明",
    strategy="direct_or_react",
    instructions=(
        "先理解用户当前的问题：能直接回答就直接回答，范围不明确先追问，"
        "只有回答依赖本校真实数据时才调用工具。"
        "根据每次工具返回的证据决定是否继续查询，不因问题标签而执行固定检查链。"
        "明确区分事实、推断和未核实项；证据不足时不要声称已完成全面检查。"
        "排课问题按问题选择日志、容量或走班数据工具，不默认检查全校。"
        "走班人数与固定任课用 lookup_walk_classes，缺年级先澄清；禁止凭经验编造根因。"
        "不要创建规则草稿。"
    ),
    allowed_tools=frozenset({
        "lookup_playbook", "lookup_schedule_setup", "lookup_teachers", "lookup_rules",
        "lookup_generation_status",
        "lookup_generation_log", "lookup_subject_capacity", "lookup_remaining_capacity",
        "lookup_slot_role_capacity", "lookup_walk_classes",
    }),
    max_steps=3,
    step_timeout_seconds=60,
    turn_timeout_seconds=90,
)

DIRECT_HARNESS = HarnessProfile(
    name="direct",
    label="快速回答",
    strategy="direct",
    instructions="直接回答当前问题，不读取学校数据，不调用工具，不创建任何草稿。",
    allowed_tools=frozenset(),
    max_steps=1,
    step_timeout_seconds=30,
    turn_timeout_seconds=45,
)

PLAN_HARNESS = replace(
    GUIDE_HARNESS,
    name='plan', label='计划模式',
    instructions=(
        '本轮为计划模式：只分析、查询和提出方案，不创建规则草稿、不执行页面操作或数据修改。'
        '先说明结论，再给必要的步骤和待确认项；简单问题直接回答，模糊问题先追问。'
        '不要把建议说成已完成；用户要求保存或执行时说明需退出计划模式并明确确认。'
        + GUIDE_HARNESS.instructions
    ),
)


def apply_assistant_mode(profile: HarnessProfile, page_context: dict | None) -> HarnessProfile:
    return PLAN_HARNESS if (page_context or {}).get('assistant_mode') == 'plan' else profile

READINESS_HARNESS = HarnessProfile(
    name="readiness",
    label="排课准备检查",
    strategy="checklist_react",
    instructions=(
        "先核对学年学期、课时课位、任教关系和规则，再按已满足、缺失、下一步输出清单。"
        "所有结论必须来自工具结果；本任务禁止创建规则草稿。"
    ),
    allowed_tools=frozenset({
        "lookup_schedule_setup", "lookup_teachers", "lookup_rules", "lookup_playbook",
    }),
    max_steps=5,
    step_timeout_seconds=75,
    turn_timeout_seconds=150,
)

DIAGNOSIS_HARNESS = HarnessProfile(
    name="diagnosis",
    label="排课故障诊断",
    strategy="evidence_first_react",
    instructions=(
        "先读取排课任务状态，再核对准备数据和规则。明确区分观测事实与推断，"
        "给出可验证的恢复步骤。班数、人数、走班任课问题查询 lookup_walk_classes；"
        "容量和求解日志按需查询，不要把准备完整或容量足够当成求解成功。"
        "本任务禁止创建规则草稿。"
    ),
    allowed_tools=frozenset({
        "lookup_generation_status", "lookup_schedule_setup", "lookup_teachers",
        "lookup_rules", "lookup_playbook",
        "lookup_generation_log", "lookup_subject_capacity", "lookup_remaining_capacity",
        "lookup_slot_role_capacity", "lookup_walk_classes",
    }),
    max_steps=6,
    step_timeout_seconds=75,
    turn_timeout_seconds=180,
)

CONFIGURATION_HARNESS = HarnessProfile(
    name="configuration",
    label="规则配置草稿",
    strategy="proposal_react",
    instructions=(
        "先查询现状并澄清范围，再生成一份可核对的规则草稿。只能调用草稿能力，"
        "不能声称已经保存；实际写入必须等待老师在独立确认接口中确认。"
    ),
    allowed_tools=frozenset({
        "lookup_schedule_setup", "lookup_teachers", "lookup_rules", "lookup_playbook",
        "propose_rules",
    }),
    max_steps=5,
    step_timeout_seconds=75,
    turn_timeout_seconds=150,
)


class HarnessRouter:
    """Map a classified intent to one server-owned harness profile."""

    profiles = MappingProxyType({
        profile.name: profile
        for profile in (
            GUIDE_HARNESS, READINESS_HARNESS, DIAGNOSIS_HARNESS, CONFIGURATION_HARNESS,
            DIRECT_HARNESS,
        )
    })

    _intent_profiles = MappingProxyType({
        AssistantIntent.GUIDE: GUIDE_HARNESS,
        AssistantIntent.READINESS: READINESS_HARNESS,
        AssistantIntent.DIAGNOSIS: DIAGNOSIS_HARNESS,
        AssistantIntent.CONFIGURATION: CONFIGURATION_HARNESS,
        AssistantIntent.UNKNOWN: GUIDE_HARNESS,
    })

    def select(self, decision: IntentDecision) -> HarnessProfile:
        if decision.route is AssistantRoute.DIRECT:
            return DIRECT_HARNESS
        # Interactive read-only topics share one bounded evidence loop. Hints
        # must not prevent the model from choosing the next query after observing
        # a result. Only server-owned tools can appear in the capability set.
        if decision.kind is not AssistantIntent.CONFIGURATION:
            return GUIDE_HARNESS
        profile = self._intent_profiles[decision.kind]
        if decision.tool_hints and decision.route not in {AssistantRoute.SUPERVISOR, AssistantRoute.WORKFLOW}:
            allowed = profile.allowed_tools.intersection(decision.tool_hints)
            if allowed:
                return replace(profile, allowed_tools=frozenset(allowed))
        return profile
