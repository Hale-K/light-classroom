"""Classify a teacher request before selecting its execution harness.

Intent classification chooses a task strategy only. Authorization remains in
the tool gateway, so a mistaken classification cannot grant extra privileges.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import asyncio
from enum import StrEnum
import logging
import re
from typing import Awaitable, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AssistantIntent(StrEnum):
    GUIDE = "guide"
    READINESS = "readiness"
    DIAGNOSIS = "diagnosis"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class ExecutionMode(StrEnum):
    QUERY = "query"
    PLANNING = "planning"


class AssistantRoute(StrEnum):
    """Execution route selected before a harness is opened."""

    DIRECT = "direct"
    AGENT = "agent"
    SUPERVISOR = "supervisor"
    WORKFLOW = "workflow"
    HUMAN_REVIEW = "human_review"


class FailureAction(StrEnum):
    RETRY = "retry"
    CREATE_FOLLOWUP = "create_followup"
    WAIT_USER = "wait_user"
    STOP = "stop"


class ReviewAction(StrEnum):
    NONE = "none"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class RouterPolicyDecision:
    action: FailureAction | ReviewAction
    reason: str
    confidence: float = 1.0

    def trace_data(self) -> dict:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
        }


@dataclass(frozen=True, slots=True)
class IntentDecision:
    kind: AssistantIntent
    confidence: float
    source: str
    needs_clarification: bool = False
    route: AssistantRoute = AssistantRoute.AGENT
    tool_hints: frozenset[str] = frozenset()
    execution_mode: ExecutionMode | None = None
    write_requested: bool = False

    @property
    def effective_mode(self) -> ExecutionMode:
        if self.execution_mode is not None:
            return self.execution_mode
        return (ExecutionMode.PLANNING if self.kind in {
            AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS, AssistantIntent.CONFIGURATION,
        } else ExecutionMode.QUERY)

    def trace_data(self) -> dict:
        return {
            "kind": self.kind.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "needs_clarification": self.needs_clarification,
            "route": self.route.value,
            "tool_hints": sorted(self.tool_hints),
            "execution_mode": self.effective_mode.value,
            "write_requested": self.write_requested,
        }


SemanticClassifier = Callable[
    [AsyncSession | None, str, str | None, list[dict]],
    Awaitable[IntentDecision | None],
]
DecisionClassifier = SemanticClassifier


class IntentGatewayService(Protocol):
    async def classify(
        self,
        session: AsyncSession | None,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision: ...


class IntentGateway:
    """Semantic intent gate with a safe guide fallback."""

    def __init__(
        self,
        semantic_classifier: SemanticClassifier | None = None,
        *,
        decision_classifier: DecisionClassifier | None = None,
        minimum_decision_confidence: float = 0.70,
        classification_timeout_seconds: float = 2.0,
    ):
        self._semantic_classifier = semantic_classifier
        self._decision_classifier = decision_classifier
        self._minimum_decision_confidence = minimum_decision_confidence
        self._classification_timeout = classification_timeout_seconds

    _SIMPLE_ARITHMETIC = re.compile(
        r"^\s*\d{1,9}\s*[+\-*/×÷]\s*\d{1,9}\s*(?:=\s*)?[?？]?\s*$"
    )
    # “当前页面内容有什么”这类问题不表达五类业务意图，答案就在本轮注入的
    # 页面上下文里；不识别会让分类器判成 unknown，落进“需要澄清”死胡同。
    _PAGE_WORDS = ("页面", "当前页", "本页", "界面")
    _PAGE_ASK_WORDS = ("有什么", "什么内容", "是什么", "干什么", "干嘛", "干啥", "功能", "作用", "介绍")

    @classmethod
    def _asks_page_description(cls, text: str) -> bool:
        return len(text) <= 30 and any(w in text for w in cls._PAGE_WORDS) and any(w in text for w in cls._PAGE_ASK_WORDS)

    @staticmethod
    def _route_for(kind: AssistantIntent, route: AssistantRoute) -> AssistantRoute:
        """把意图规范化为可观测的执行模式；权限仍由 Harness/ToolGateway 控制。"""
        if route is AssistantRoute.DIRECT:
            return route
        if kind in {AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS}:
            return AssistantRoute.AGENT
        if kind is AssistantIntent.CONFIGURATION:
            return AssistantRoute.HUMAN_REVIEW
        return route

    def _resolve_execution(self, decision: IntentDecision, query: str) -> IntentDecision:
        """Keep topic labels for tracing, not as mandatory workflow commands."""
        if decision.needs_clarification or decision.kind is AssistantIntent.UNKNOWN:
            return replace(decision, needs_clarification=True, route=AssistantRoute.AGENT)
        if decision.confidence < self._minimum_decision_confidence:
            return replace(decision, needs_clarification=True, route=AssistantRoute.AGENT)
        # A proposal and an actual edit are separate from execution complexity.
        # Classifier topic labels can never confer tool permissions.
        return replace(decision, route=AssistantRoute.DIRECT if decision.route is AssistantRoute.DIRECT
                       and decision.effective_mode is ExecutionMode.QUERY else AssistantRoute.AGENT,
                       write_requested=self._requests_write(query))

    @staticmethod
    def _requests_write(text: str) -> bool:
        if re.search(r"(?:只|仅)(?:做建议|查询|分析|讨论|提供方案)|(?:不|不要)(?:保存|执行|修改(?:数据|配置|规则))|(?:如果|假如).{0,30}(?:影响|会怎样|会怎么样)", text):
            return False
        # "个人保存课表" and "已保存课表" name a stored record, not
        # an imperative to persist it. A later explicit edit remains detectable.
        text = re.sub(r'(?:个人保存|已保存|保存的)(?=课表)', '现有', text)
        if re.search(r"(?:怎么|如何|能否|怎样).{0,8}(?:修改|保存|删除|创建)", text):
            return False
        if '方案' in text and not re.search(r'(?:保存|应用|执行).{0,8}(?:方案|规则|配置)', text):
            return False
        if not re.search(r'查询|查看|有哪些|什么意思|现有|已配置', text) and re.search(
                r'(?:周[一二三四五六日天]|星期[一二三四五六日天]|\d+节).{0,15}(?:禁排|不要安排)|(?:禁排|不要安排).{0,15}(?:周[一二三四五六日天]|星期[一二三四五六日天])', text):
            return True
        return bool(re.search(r"(?:请|帮我|直接|立即|确认)?(?:保存|执行|应用|创建|修改|新增|删除).{0,12}(?:规则|课表|任课|教师|学生|数据|配置)|把.{0,12}(?:规则|课表|任课|配置).{0,8}(?:修改|改成|改为|保存|删除)|规则组.{0,15}(?:不要安排|禁排|连堂)", text))

    @staticmethod
    def _structural_planning(text: str, turns: list[dict]) -> bool:
        if IntentGateway._explicit_query(text):
            return False
        if re.search(r'(?:不要|不用|无需)(?:规划|制定方案|全面检查).{0,12}只(?:查|解释|告诉)', text):
            return False
        if len(text) < 45 and re.search(r'(?:规划|计划)(?:模式|功能).{0,10}(?:是什么|什么意思|怎么用|如何使用)', text):
            return False
        if re.search(r"(?:[2-9两二三四五六七八九]|多个|几)(?:个|套|种)?(?:课时|排课|教学)?(?:方案|计划)|(?:规划|制定方案|全面验收|全面检查|系统验收|逐步执行)", text):
            return True
        if re.search(r"(?:全校|所有班|全部班|整体).{0,30}(?:汇总|冲突|检查|审计|排课准备)", text):
            return True
        if (re.search(r"先.{1,40}(?:再|然后|接着)", text)
                or (len(text) > 65 and sum(word in text for word in ("同时", "必须", "方案", "分别", "核对", "可选")) >= 2)):
            return True
        if re.search(r"(?:第[一二三123]套|第二个方案|第三个方案|按刚才方案|继续执行|继续规划)", text):
            previous = " ".join(str(item.get('content') or '') for item in turns[:-1][-4:])
            return bool(re.search(r"方案|计划|规划|步骤", previous))
        return IntentGateway._requests_write(text)

    @staticmethod
    def _explicit_query(text: str) -> bool:
        # One student's saved records and current environment are focused
        # lookups even with a long field list or a previous planning turn.
        if (len(text) <= 180 and not IntentGateway._requests_write(text)
                and not re.search(r'全校|所有班|全部班|冲突|方案|规划|全面|分析|比较|先.{1,40}(?:再|然后)', text)
                and re.search(r'个人(?:保存)?课表|当前学校.{0,20}(?:课表模式|高考模式)', text)
                and re.search(r'查|是什么|分别是什么', text)):
            return True
        if len(text) < 45 and re.search(r'(?:规划|计划)(?:模式|功能).{0,10}(?:是什么|什么意思|怎么用|如何使用)', text):
            return True
        return bool(len(text) < 65 and not re.search(r'全校|所有|全部|汇总|冲突', text)
            and re.search(r'(?:不要|不用|无需)(?:规划|制定方案|全面检查).{0,12}只(?:查|解释|告诉)', text))

    @staticmethod
    def failure_policy(*, retry_count: int, max_retries: int, missing: tuple[str, ...] = ()) -> RouterPolicyDecision:
        """选择单个子任务失败后的动作；不直接执行任何副作用。"""
        if missing:
            return RouterPolicyDecision(
                FailureAction.WAIT_USER,
                "子任务缺少用户或业务配置，等待补充后再继续",
            )
        if retry_count < max(0, max_retries):
            return RouterPolicyDecision(FailureAction.RETRY, "仍有重试预算")
        return RouterPolicyDecision(FailureAction.CREATE_FOLLOWUP, "重试预算已用尽，交由 Supervisor 创建补充任务")

    @staticmethod
    def review_policy(*, failed_tasks: tuple[str, ...] = (), missing: tuple[str, ...] = (), mutates_data: bool = False) -> RouterPolicyDecision:
        """判断结果是否需要人工复核；写入类动作默认必须人工确认。"""
        if mutates_data:
            return RouterPolicyDecision(ReviewAction.REQUIRED, "结果可能改变业务数据，必须人工确认")
        if failed_tasks or missing:
            return RouterPolicyDecision(ReviewAction.RECOMMENDED, "结果包含失败项或缺失项，建议人工复核")
        return RouterPolicyDecision(ReviewAction.NONE, "只读检查已完成且没有未决项")

    async def classify(
        self,
        session: AsyncSession | None,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision:
        text = " ".join((query or "").split())
        turns = list((recent_turns or [])[-6:])
        deadline = asyncio.get_running_loop().time() + self._classification_timeout

        # Avoid loading the embedding model for requests whose complexity is
        # structurally trivial and which never need school data or tools.
        if self._SIMPLE_ARITHMETIC.fullmatch(text):
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=1.0,
                source="fast_path",
                route=AssistantRoute.DIRECT,
            )
        if self._asks_page_description(text):
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=1.0,
                source="fast_path",
                route=AssistantRoute.AGENT,
            )

        # Clear structural demands are resolved locally even when the optional
        # classifier is unavailable. Remaining paraphrases use semantic services.
        if self._structural_planning(text, turns):
            return IntentDecision(AssistantIntent.GUIDE, 1.0, 'task_structure',
                execution_mode=ExecutionMode.PLANNING, write_requested=self._requests_write(text))
        if self._explicit_query(text):
            return IntentDecision(AssistantIntent.GUIDE, 1.0, 'explicit_query',
                execution_mode=ExecutionMode.QUERY)

        # Jev or another bounded decision service is optional. Any unavailable
        # or low-confidence result falls through to the existing pgvector path.
        if self._decision_classifier is not None:
            try:
                decision = await asyncio.wait_for(
                    self._decision_classifier(session, query, page_path, turns),
                    timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                )
            except Exception as exc:  # decision layer must never block the assistant
                logger.warning("assistant.router decision layer unavailable: %s", exc)
                decision = None
            if decision is not None and (decision.needs_clarification
                    or decision.kind is AssistantIntent.UNKNOWN
                    or decision.confidence >= self._minimum_decision_confidence):
                return self._resolve_execution(decision, text)
            if decision is not None:
                logger.info(
                    "assistant.router decision fallback source=%s confidence=%.3f threshold=%.3f",
                    decision.source,
                    decision.confidence,
                    self._minimum_decision_confidence,
                )

        if self._semantic_classifier is not None and asyncio.get_running_loop().time() < deadline:
            try:
                semantic = await asyncio.wait_for(
                    self._semantic_classifier(session, query, page_path, turns),
                    timeout=max(0.0, deadline - asyncio.get_running_loop().time()),
                )
            except Exception as exc:
                logger.warning("assistant.router semantic fallback: %s", type(exc).__name__)
                semantic = None
            if semantic is not None:
                return self._resolve_execution(semantic, text)

        if text:
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=0.55,
                source="safe_fallback",
                route=AssistantRoute.AGENT,
            )
        return IntentDecision(
            kind=AssistantIntent.UNKNOWN,
            confidence=0.0,
            source="empty",
            needs_clarification=True,
        )
