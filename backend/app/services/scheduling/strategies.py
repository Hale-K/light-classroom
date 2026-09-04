"""可注册、可组合的排课软约束策略。"""
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol


@dataclass(frozen=True)
class CandidateContext:
    same_subject_today: int
    class_day_load: int
    teacher_day_load: int
    period: int
    class_gap_penalty: int
    teacher_gap_penalty: int
    teacher_adjacent_count: int
    adjacent_day_same_period_count: int = 0
    same_subject_same_period_days: int = 0
    teacher_slot_week_load: int = 0
    random_tiebreak: int = 0


@dataclass(frozen=True)
class StrategyOption:
    code: str
    name: str
    description: str


class ScheduleStrategy(Protocol):
    option: StrategyOption

    def score(self, context: CandidateContext) -> tuple[int, ...]: ...

    def optimize(self, items: list[Any], repair_class_gaps: Callable[[list[Any]], list[Any]]) -> list[Any]: ...


_STRATEGY_REGISTRY: dict[str, type[ScheduleStrategy]] = {}


class BaseScheduleStrategy:
    def optimize(self, items: list[Any], repair_class_gaps: Callable[[list[Any]], list[Any]]) -> list[Any]:
        return items


def register_schedule_strategy(strategy_type: type[ScheduleStrategy]) -> type[ScheduleStrategy]:
    code = strategy_type.option.code
    if code in _STRATEGY_REGISTRY:
        raise ValueError(f"排课策略 {code} 已注册")
    _STRATEGY_REGISTRY[code] = strategy_type
    return strategy_type


@register_schedule_strategy
class DailyBalanceStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="daily_balance",
        name="均衡优先",
        description="均衡班级和教师每日课时，避免课程集中在少数日期。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (context.same_subject_today * 100, context.class_day_load + context.teacher_day_load)


@register_schedule_strategy
class CrossDayVarietyStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="cross_day_variety",
        name="跨天错峰",
        description="避免同一科目连续多天固定在同一节次，打散每日课程顺序。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (
            context.adjacent_day_same_period_count * 100,
            context.same_subject_same_period_days,
        )


@register_schedule_strategy
class RandomTieBreakStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="random_tiebreak",
        name="同分随机",
        description="在约束得分相同的位置中随机选择，避免每次形成机械化课表。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (context.random_tiebreak,)


@register_schedule_strategy
class ClassCompactStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="class_compact",
        name="班级紧凑",
        description="优先减少班级课表中间空堂，并尽量使用较早节次。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (context.class_gap_penalty, context.period)


@register_schedule_strategy
class TeacherFriendlyStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="teacher_friendly",
        name="教师友好",
        description="均衡教师单日负担，减少连续授课和教师课表空洞。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (
            context.teacher_day_load,
            context.teacher_adjacent_count,
            context.teacher_gap_penalty,
        )


@register_schedule_strategy
class ResourceTightStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="resource_tight",
        name="资源紧张·多排",
        description="允许同一班同一学科一天安排多节，并提高教师日课时上限；仍禁止同一教师同一时段重复授课。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (context.class_day_load + context.teacher_day_load, context.period)


@register_schedule_strategy
class CrossClassGapRepairStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="cross_class_gap_repair",
        name="跨班换位修复",
        description="初排后联动移动教师在其他班的课程，修复班级课表中间空堂。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return ()

    def optimize(self, items: list[Any], repair_class_gaps: Callable[[list[Any]], list[Any]]) -> list[Any]:
        return repair_class_gaps(items)


@dataclass(frozen=True)
class CompositeScheduleStrategy:
    strategies: tuple[ScheduleStrategy, ...]

    @property
    def codes(self) -> list[str]:
        return [strategy.option.code for strategy in self.strategies]

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return tuple(
            value
            for strategy in self.strategies
            for value in strategy.score(context)
        ) + (context.period,)

    def optimize(self, items: list[Any], repair_class_gaps: Callable[[list[Any]], list[Any]]) -> list[Any]:
        result = items
        for strategy in self.strategies:
            result = strategy.optimize(result, repair_class_gaps)
        return result


def list_schedule_strategies() -> list[StrategyOption]:
    return [strategy_type.option for strategy_type in _STRATEGY_REGISTRY.values()]


def build_schedule_strategy(codes: list[str] | None = None) -> CompositeScheduleStrategy:
    # 服务层保持兼容旧调用方；HTTP 接口和前端规则设计器会显式传入
    # “跨天错峰 + 班级紧凑 + 跨班空档修复”这一套高一默认组合。
    selected_codes = list(dict.fromkeys(codes or [
        "daily_balance", "cross_day_variety", "random_tiebreak",
    ]))
    unknown = [code for code in selected_codes if code not in _STRATEGY_REGISTRY]
    if unknown:
        raise ValueError(f"未知排课策略：{', '.join(unknown)}")
    return CompositeScheduleStrategy(tuple(_STRATEGY_REGISTRY[code]() for code in selected_codes))


@register_schedule_strategy
class SlotTeacherSpreadStrategy(BaseScheduleStrategy):
    option = StrategyOption(
        code="slot_teacher_spread",
        name="节次摊散",
        description="同一节次（如班主任禁排后的第5节）尽量摊给不同教师，避免集中压给同一个人。",
    )

    def score(self, context: CandidateContext) -> tuple[int, ...]:
        return (context.teacher_slot_week_load * 10,)
