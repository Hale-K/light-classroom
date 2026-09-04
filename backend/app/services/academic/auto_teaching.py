"""Automatic teaching-assignment matching with explicit teacher/class scope rules."""
def suggested_weekly_periods(student_count: int | None, base: int = 4) -> int:
    """按班级学生数给出建议每周课时（学生多→课时多，学生少→课时少）。

    分档规则（可后续按学校配置调整）：
      - 人数未知（None）或 30 人以下 → base - 1
      - 30~44 人 → base
      - 45 人及以上 → base + 1
    """
    if student_count is None:
        return max(1, base - 1)
    if student_count >= 45:
        return base + 1
    if student_count >= 30:
        return base
    return max(1, base - 1)

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TeacherScopeRule:
    teacher_id: int
    class_id: int
    mode: str
    weekly_periods: int | None = None
    subject_id: int | None = None
    fixed_weekday: int | None = None
    fixed_period: int | None = None


def target_class_ids(assignments: Iterable[Mapping], class_ids: Iterable[int]) -> list[int]:
    """Limit automatic matching to classes with data in the current scope."""
    scoped_ids = {int(item["class_id"]) for item in assignments}
    return sorted({int(class_id) for class_id in class_ids if int(class_id) in scoped_ids})


def apply_subject_periods(
    assignments: Iterable[Mapping],
    subject_weekly_periods: Mapping[int, int],
) -> list[dict]:
    """Build the planning view with configured periods applied to existing relations."""
    result = []
    for item in assignments:
        row = dict(item)
        subject_id = int(row["subject_id"])
        if subject_id in subject_weekly_periods:
            row["weekly_periods"] = int(subject_weekly_periods[subject_id])
        result.append(row)
    return result


def assignments_outside_rebuild_scope(
    assignments: Iterable[Mapping],
    class_ids: Iterable[int],
    subject_ids: Iterable[int],
) -> list[dict]:
    """重编当前班级/学科时，仅保留范围之外的任教关系作为教师负荷。"""
    scoped_classes = {int(class_id) for class_id in class_ids}
    scoped_subjects = {int(subject_id) for subject_id in subject_ids}
    return [
        dict(item)
        for item in assignments
        if int(item["class_id"]) not in scoped_classes or int(item["subject_id"]) not in scoped_subjects
    ]


def build_auto_assignments(
    assignments: Iterable[Mapping],
    class_ids: Iterable[int],
    rules: Iterable[TeacherScopeRule],
    weekly_periods: int = 4,
    max_weekly_periods: int = 32,
    subject_ids: Iterable[int] | None = None,
    subject_weekly_periods: Mapping[int, int] | None = None,
    subject_max_weekly_periods: Mapping[int, int] | None = None,
    student_counts: Mapping[int, int] | None = None,
    days: int = 5,
    periods_per_day: int = 7,
    max_same_subject_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_class_lessons_per_day: int | None = None,
    forbidden_slots: Iterable[tuple[int, int]] = (),
    teacher_subject_fallback: Mapping[int, Iterable[int]] | None = None,
    eligible_teacher_ids: Iterable[int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Fill missing class/subject relations while honoring teacher scope rules.

    A teacher's existing assignments define the subjects they are qualified for.
    This naturally supports reciprocal A/B teaching: each teacher can carry their
    own subject into the other's class when both classes are missing that subject.
    teacher_subject_fallback（如教研组成员资格）在已有任教关系之外补充资质，
    使清空任教关系后仍能从零冷启动编排。
    """
    eligible_ids = {int(item) for item in eligible_teacher_ids} if eligible_teacher_ids is not None else None
    rows = [
        item for item in assignments
        if item.get("teacher_id") is not None
        and (eligible_ids is None or int(item["teacher_id"]) in eligible_ids)
    ]
    teacher_subjects: dict[int, set[int]] = defaultdict(set)
    teacher_load: dict[int, int] = defaultdict(int)
    existing = {(int(item["class_id"]), int(item["subject_id"])) for item in rows}
    # 时间结构推导的周上限：同科每日上限 × 教学日 = 单学科周课时上限
    same_subject_weekly_cap = max_same_subject_per_day * days if max_same_subject_per_day else None
    teacher_weekly_cap = max_teacher_lessons_per_day * days if max_teacher_lessons_per_day else None
    class_weekly_cap = max_class_lessons_per_day * days if max_class_lessons_per_day else None
    class_load: dict[int, int] = defaultdict(int)
    forbidden = set(forbidden_slots or ())
    for item in rows:
        teacher_id = int(item["teacher_id"])
        teacher_subjects[teacher_id].add(int(item["subject_id"]))
        teacher_load[teacher_id] += int(item.get("weekly_periods") or weekly_periods)
    for item in rows:
        class_load[int(item["class_id"])] += int(item.get("weekly_periods") or weekly_periods)
    deny_pairs: set[tuple[int, int]] = set()
    deny_subject_pairs: set[tuple[int, int, int]] = set()
    pin_rules: list[TeacherScopeRule] = []
    # 只有明确指定学科的搭班规则才覆盖该学科课时。
    # 未指定学科的规则仅表示教师与班级的允许/禁止关系，不能把一门课的课时
    # 错误套用到该教师后来匹配到的其他学科上。
    period_by_subject_pair: dict[tuple[int, int, int], int] = {}
    for rule in rules:
        if rule.mode == "deny":
            if rule.subject_id is None:
                deny_pairs.add((rule.teacher_id, rule.class_id))
            else:
                deny_subject_pairs.add((rule.teacher_id, rule.subject_id, rule.class_id))
        elif rule.mode == "allow":
            # allow = 固定任教(必须带该班/该科)：优先落位，但不限制教师承担其他班级
            pin_rules.append(rule)
        if rule.weekly_periods and rule.subject_id is not None:
            period_by_subject_pair[(rule.teacher_id, rule.subject_id, rule.class_id)] = rule.weekly_periods

    if teacher_subject_fallback:
        for teacher_id, qualified in teacher_subject_fallback.items():
            if eligible_ids is not None and int(teacher_id) not in eligible_ids:
                continue
            teacher_subjects[int(teacher_id)].update(int(sid) for sid in qualified)
    if eligible_ids is not None:
        teacher_subjects = {
            teacher_id: qualified
            for teacher_id, qualified in teacher_subjects.items()
            if teacher_id in eligible_ids
        }
    subjects = sorted({int(item["subject_id"]) for item in rows})
    if subject_ids is not None:
        selected_subjects = {int(subject_id) for subject_id in subject_ids}
        subjects = [subject_id for subject_id in subjects if subject_id in selected_subjects]
    if not subjects and subject_ids is not None:
        # 全新年级（没有任何已有任教关系）时，学科集合为空；
        # 用调用方传入的学科范围兜底，让自动生成能从零开始
        subjects = sorted({int(subject_id) for subject_id in subject_ids})
    if not subjects:
        # 冷启动：无已有任教关系且未指定学科范围时，用教师资质（教研组成员）推导学科集合
        subjects = sorted({subject_id for qualified in teacher_subjects.values() for subject_id in qualified})
    created: list[dict] = []
    skipped: list[dict] = []

    def _teacher_limit(subject_id: int) -> int:
        limit = (subject_max_weekly_periods or {}).get(subject_id, max_weekly_periods)
        if teacher_weekly_cap is not None:
            limit = min(limit, teacher_weekly_cap)
        return limit

    # 固定任教(allow)规则优先落位：保证「必须带」的班级先占位，再进行常规匹配
    scoped = set(int(cid) for cid in class_ids)
    for rule in pin_rules:
        if rule.class_id not in scoped:
            continue
        if any(int(row["teacher_id"]) == rule.teacher_id and int(row["class_id"]) == rule.class_id for row in rows):
            continue  # 已有该教师在该班任教，固定要求已满足
        student_count = (student_counts or {}).get(rule.class_id)
        pin_subjects = [rule.subject_id] if rule.subject_id is not None else [
            sid for sid in subjects if sid in teacher_subjects.get(rule.teacher_id, set())
        ]
        placed = False
        for sid in pin_subjects:
            if (rule.class_id, sid) in existing:
                continue
            if sid not in teacher_subjects.get(rule.teacher_id, set()):
                continue
            if (rule.teacher_id, rule.class_id) in deny_pairs or (rule.teacher_id, sid, rule.class_id) in deny_subject_pairs:
                continue
            suggested = suggested_weekly_periods(student_count, base=weekly_periods)
            periods = period_by_subject_pair.get(
                (rule.teacher_id, sid, rule.class_id),
                (subject_weekly_periods or {}).get(sid, suggested),
            )
            if same_subject_weekly_cap is not None and periods > same_subject_weekly_cap:
                periods = same_subject_weekly_cap
            if teacher_load[rule.teacher_id] + periods > _teacher_limit(sid):
                continue
            if class_weekly_cap is not None and class_load[rule.class_id] + periods > class_weekly_cap:
                continue
            created.append({
                "teacher_id": rule.teacher_id,
                "subject_id": sid,
                "class_id": rule.class_id,
                "weekly_periods": periods,
                "student_count": student_count,
                "suggested_weekly_periods": suggested,
            })
            existing.add((rule.class_id, sid))
            teacher_load[rule.teacher_id] += periods
            class_load[rule.class_id] += periods
            placed = True
            break
        if not placed:
            skipped.append({
                "class_id": rule.class_id,
                "subject_id": rule.subject_id if rule.subject_id is not None else (pin_subjects[0] if pin_subjects else 0),
                "reason": "固定任教规则无法满足（教师无资质、课时上限或班级容量不足）",
            })

    for class_id in class_ids:
        for subject_id in subjects:
            if (class_id, subject_id) in existing:
                continue
            candidates = []
            capacity_blocked = False
            for teacher_id, qualified_subjects in teacher_subjects.items():
                if subject_id not in qualified_subjects:
                    continue
                if (teacher_id, class_id) in deny_pairs or (teacher_id, subject_id, class_id) in deny_subject_pairs:
                    continue
                # 建议课时：优先按学生数分档，其次学科配置，最后默认
                student_count = (student_counts or {}).get(class_id)
                suggested = suggested_weekly_periods(student_count, base=weekly_periods)
                periods = period_by_subject_pair.get(
                    (teacher_id, subject_id, class_id),
                    (subject_weekly_periods or {}).get(subject_id, suggested),
                )
                teacher_weekly_limit = (subject_max_weekly_periods or {}).get(subject_id, max_weekly_periods)
                if teacher_weekly_cap is not None:
                    teacher_weekly_limit = min(teacher_weekly_limit, teacher_weekly_cap)
                if teacher_load[teacher_id] + periods > teacher_weekly_limit:
                    continue
                # 时间结构：同科每周上限（同科每日上限 × 教学日）与班级周容量
                if same_subject_weekly_cap is not None and periods > same_subject_weekly_cap:
                    periods = same_subject_weekly_cap
                if class_weekly_cap is not None and class_load[class_id] + periods > class_weekly_cap:
                    capacity_blocked = True
                    continue
                if forbidden and any(
                    slot[0] == class_id for slot in forbidden
                ):
                    # 禁排时段按（班级, 节次）记录：仅作提示，不阻断编排
                    pass
                # 只按当前周课时负荷分配；教师可承担多个班，班级数量不设硬上限。
                candidates.append((teacher_load[teacher_id], teacher_id, periods, student_count))
            if not candidates:
                reasons = []
                if capacity_blocked:
                    reasons.append(f"班级周课时已达上限 {class_weekly_cap} 节")
                elif not any(
                    teacher_id in teacher_subjects and subject_id in teacher_subjects[teacher_id]
                    for teacher_id in teacher_subjects
                ):
                    reasons.append("没有可教该学科的教师")
                else:
                    reasons.append("没有符合授课范围或课时上限的教师")
                skipped.append({"class_id": class_id, "subject_id": subject_id, "reason": "；".join(reasons)})
                continue
            _, teacher_id, periods, _ = min(candidates)
            row = {
                "teacher_id": teacher_id,
                "subject_id": subject_id,
                "class_id": class_id,
                "weekly_periods": periods,
                "student_count": student_count,
                "suggested_weekly_periods": suggested,
            }
            created.append(row)
            existing.add((class_id, subject_id))
            teacher_load[teacher_id] += periods
            class_load[class_id] += periods
    return created, skipped
