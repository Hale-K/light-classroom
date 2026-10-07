"""教师档案 API：组织岗位、任教班级、当周排课统计、个人周课表。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.api.v1.scheduling import _load_grid_config
from app.db.session import get_session
from app.models.enums import BaseUserRole, EveningParity, UserStatus, WeekParity
from app.models.gaokao import TeachingClass, TeachingClassSchedule
from app.models.org import (
    Class,
    CourseHourPlan,
    OrganizationUnit,
    Schedule,
    StaffAppointment,
    Subject,
    TeachingAssignment,
    TenantConfig,
    User,
)

router = APIRouter(prefix="/teacher-profiles", tags=["教师档案"])


def _grid_slots_per_class(grid: dict[str, Any]) -> float:
    """一套课位结构下一周、一个班应有的课位数（单双周各记 0.5）。无课时方案时作回退。"""
    daytime = sum(int(x or 0) for x in (grid.get("daily_periods") or [])[:7])
    odd = sum(int(x or 0) for x in (grid.get("evening_daily_periods_odd") or [])[:7])
    even = sum(int(x or 0) for x in (grid.get("evening_daily_periods_even") or [])[:7])
    return float(daytime) + (odd + even) / 2.0


def _plan_equivalent_weekly(plan: CourseHourPlan) -> float:
    """课时方案折合周课时：白天（含周六）按录入节数；晚自习单/双周各 0.5，每周都上记 1。"""
    daytime = float(plan.weekday_periods or 0) + float(plan.saturday_periods or 0)
    if daytime <= 0:
        daytime = float(plan.weekly_periods or 0)
    odd = int(plan.evening_periods_odd or 0)
    even = int(plan.evening_periods_even or 0)
    mode = plan.evening_parity
    mode_val = mode.value if isinstance(mode, EveningParity) else str(mode or EveningParity.all.value)
    if mode_val == EveningParity.either.value and odd and even:
        evening = 0.5
    elif odd and even:
        evening = float(max(odd, even))
    else:
        evening = (0.5 if odd else 0.0) + (0.5 if even else 0.0)
    return daytime + evening


_SCHEDULE_UNIT = func.sum(
    case(
        (Schedule.week_parity.in_([WeekParity.odd, WeekParity.even, "odd", "even"]), 0.5),
        else_=1.0,
    )
)


# ---------------------------------------------------------------------------
# 默认筛选元信息
# ---------------------------------------------------------------------------


async def _defaults(session: AsyncSession, tenant_id: int) -> dict[str, Any]:
    """返回当前届别、当前学年、当前学期默认值。

    兼容多种实际存在的 config_key：
      - academic_years     （系统设置-届次管理写入的真实key，含current_entry_year/current_academic_year/current_term）
      - school_settings    （旧格式，兼容）
      - current_cohort / current_grade_cohort （旧格式，兼容）

    届别合法性校验：
      若 TenantConfig 中配置的 current_entry_year（例如"2026"）在 OrganizationUnit 中
      不存在对应的 active grade_group / grade / cohort 节点（即用户已删除该届），
      则自动回退为"现有 active 年级节点中 cohort_label 数字最大的一届"（最近一届）。
      避免届筛选下拉框中显示"裸数字2026"而没有实际届别组织节点的问题。
    """
    stmt = select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key.in_([
            "academic_years",      # <- 实际数据库里用的是这个！
            "current_cohort",      # 兼容（优先）
            "current_grade_cohort",
            "school_settings",     # 旧格式，兼容
        ]),
    )
    rows = (await session.execute(stmt)).scalars().all()
    entry_year: int | None = None
    academic_year: str | None = None
    term: str = "1"
    for row in rows:
        if not isinstance(row.config_value, dict):
            continue
        cfg = row.config_value
        if row.config_key in {"current_cohort", "current_grade_cohort"}:
            entry_year = cfg.get("entry_year") or entry_year
        elif row.config_key == "academic_years":
            # 系统设置里真实存在的key，优先级最高
            entry_year = cfg.get("current_entry_year") or cfg.get("entry_year") or entry_year
            academic_year = cfg.get("current_academic_year") or cfg.get("current_year") or academic_year
            term = str(cfg.get("current_term") or term)
        else:
            # school_settings 里可能同时有三者
            entry_year = cfg.get("current_entry_year") or cfg.get("entry_year") or entry_year
            academic_year = cfg.get("current_academic_year") or academic_year
            term = str(cfg.get("current_term") or term)

    # ---- 届别合法性校验 + 回退到最近一届 ----
    # 1) 加载租户内所有 active grade 组织节点及对应的 cohort_label
    existing_orgs_stmt = select(OrganizationUnit.cohort_label).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type.in_(["grade", "cohort", "grade_group"]),
        OrganizationUnit.status == "active",
        OrganizationUnit.cohort_label.isnot(None),
    )
    existing_cohort_labels: list[str] = [
        r for r, in (await session.execute(existing_orgs_stmt)).fetchall() if r
    ]
    existing_cohort_years: list[int] = []
    for cl in existing_cohort_labels:
        try:
            existing_cohort_years.append(int(cl))
        except (TypeError, ValueError):
            continue
    existing_cohort_years = sorted(set(existing_cohort_years), reverse=True)  # 从大到小(最近一届在前)

    # 2) 如果配置的 entry_year 不在现有节点中，回退到最近一届（最大年份）
    if existing_cohort_years:
        if (entry_year is None) or (entry_year not in existing_cohort_years):
            entry_year = existing_cohort_years[0]
    # else: 组织节点中完全没有配置届别标签（罕见），保留 None 让前端处理

    # 兜底：按 entry_year 推导学年
    if entry_year and not academic_year:
        academic_year = f"{entry_year}-{entry_year + 1}"
    return {
        "entry_year": entry_year,
        "academic_year": academic_year,
        "term": term,
    }


def _position_label(code: str | None) -> str:
    mapping = {
        "principal": "校长",
        "director": "主任",
        "academic_director": "教务主任",
        "head_teacher": "班主任",
        "moral_education": "德育主任",
        "member": "组织成员",
    }
    return mapping.get(code or "", "组织成员")


@router.get("/filters", summary="获取筛选条件默认值与候选年级")
async def filters_meta(
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
    user=Depends(get_current_user),
):
    defaults = await _defaults(session, tenant_id)
    # 年级列表 + 绑定的cohort_label
    stmt = select(
        OrganizationUnit.id.label("org_id"),
        OrganizationUnit.name,
        OrganizationUnit.cohort_label,
        OrganizationUnit.academic_year,
    ).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type.in_(["grade", "cohort"]),
        OrganizationUnit.status == "active",
    ).order_by(OrganizationUnit.sort_order, OrganizationUnit.name)
    orgs = (await session.execute(stmt)).mappings().all()
    cohort_groups: dict[str, Any] = {}
    for o in orgs:
        if o["cohort_label"]:
            cohort_groups.setdefault(o["cohort_label"], []).append(dict(o))
    # 另一种情况：按年级层（Grade表）组织
    from app.models.org import Grade
    grades = (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()
    # 年级筛选只展示「年级管理中心下已建年级部」的年级;空壳年级(无年级部)不进下拉
    grade_unit_names = [u.name for u in (await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.status == "active",
    ))).scalars().all()]
    def _grade_has_unit(g: Grade) -> bool:
        key = next((k for k in ("高一", "高二", "高三") if k in g.name), None)
        return key is None or any(key in name for name in grade_unit_names)
    grade_list = [{"grade_id": g.id, "name": g.name, "level": g.level} for g in grades if _grade_has_unit(g)]
    # 学科是全局字典，不带租户字段；实际可任教科目仍由列表接口按租户任教关系过滤。
    subjects = (await session.execute(select(Subject).order_by(Subject.name))).scalars().all()
    subject_list = [{"subject_id": s.id, "name": s.name} for s in subjects]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "defaults": defaults,
            "cohort_orgs": cohort_groups,
            "grades": grade_list,
            "subjects": subject_list,
        },
    }


# ---------------------------------------------------------------------------
# 教师档案列表
# ---------------------------------------------------------------------------


@router.get("", summary="教师档案列表（带排课统计）")
async def list_teacher_profiles(
    only_head_teacher: bool = Query(default=False, description="仅显示班主任"),
    subject_id: int | None = Query(default=None, description="按任教科目筛选"),
    grade_id: int | None = Query(default=None, description="按行政年级筛选"),
    cohort_entry_year: int | None = Query(default=None, description="届别(入学年份)筛选，默认取系统当前届"),
    academic_year: str | None = Query(default=None, description="学年，默认取配置学年"),
    term: str | None = Query(default=None, pattern="^[12]$", description="学期，默认取配置"),
    keyword: str | None = Query(default=None, description="姓名关键词"),
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
    user=Depends(get_current_user),
):
    defaults = await _defaults(session, tenant_id)
    term = term or defaults["term"]
    if not academic_year:
        academic_year = defaults["academic_year"]
    if cohort_entry_year is None:
        cohort_entry_year = defaults["entry_year"]

    # 找年级组织节点（筛选"XX年级部"所属的org_id）
    cohort_org_ids: set[int] = set()
    grade_org_ids: set[int] = set()
    if cohort_entry_year is not None or grade_id is not None:
        where = [
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.unit_type.in_(["grade", "cohort"]),
            OrganizationUnit.status == "active",
        ]
        if cohort_entry_year is not None:
            where.append(OrganizationUnit.cohort_label == str(cohort_entry_year))
        if grade_id is not None:
            # 按行政年级：取 Class 中 grade_id 关联到对应的年级部名称做 LIKE（通过 cohort_label 或名称相似匹配）
            g_row = (await session.execute(select(Class).where(
                Class.tenant_id == tenant_id, Class.grade_id == grade_id,
            ).limit(1))).scalar_one_or_none()
            if g_row:
                # 以班级名前缀如"高一(1)班" → "高一"匹配年级部名
                prefix = g_row.name.split("(")[0][:2] if "(" in g_row.name else g_row.name[:2]
                where.append(OrganizationUnit.name.contains(prefix))
        org_stmt = select(OrganizationUnit.id).where(and_(*where))
        cohort_org_ids = {r for r, in (await session.execute(org_stmt)).fetchall()}
    # grade_id 关联班级的 head_teacher_id 筛选用（在后续 WHERE IN 中）
    head_teacher_ids_by_grade: set[int] = set()
    if grade_id is not None:
        ht_stmt = select(Class.head_teacher_id).where(
            Class.tenant_id == tenant_id,
            Class.grade_id == grade_id,
            Class.academic_year == academic_year,
            Class.term == term,
            Class.head_teacher_id.isnot(None),
        )
        head_teacher_ids_by_grade = {r for r, in (await session.execute(ht_stmt)).fetchall() if r}

    # 1) 载入所有教师（再按条件过滤以简化逻辑）
    # 教师档案只面向可授课账号；校长、主任等管理账号不进入教师档案。
    stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.role == BaseUserRole.teacher,
        User.status == UserStatus.active,
    )
    if keyword:
        stmt = stmt.where(User.name.contains(keyword))
    teachers = (await session.execute(stmt)).scalars().all()
    teacher_ids = {t.id for t in teachers}

    # 2) 班级信息（按grade_id筛班主任）
    class_map: dict[int, Class] = {}
    class_stmt = select(Class).where(
        Class.tenant_id == tenant_id,
        Class.academic_year == academic_year,
        Class.term == term,
    )
    for c in (await session.execute(class_stmt)).scalars().all():
        class_map[c.id] = c
    head_teacher_ids = {c.head_teacher_id for c in class_map.values() if c.head_teacher_id}

    # 3) StaffAppointment 任命
    appts_stmt = select(StaffAppointment, OrganizationUnit).join(
        OrganizationUnit, StaffAppointment.organization_unit_id == OrganizationUnit.id,
    ).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.staff_id.in_(teacher_ids),
        StaffAppointment.status == "active",
    ).order_by(OrganizationUnit.sort_order, OrganizationUnit.name)
    staff_orgs: dict[int, list[tuple[StaffAppointment, OrganizationUnit]]] = defaultdict(list)
    for appt, org in (await session.execute(appts_stmt)).all():
        staff_orgs[appt.staff_id].append((appt, org))

    # 4) TeachingAssignment —— 任课关系严格按学年、学期隔离
    def _ta_where(base_where: list, ay: str | None, tm: str | None):
        w = list(base_where)
        if ay:
            w.append(TeachingAssignment.academic_year == ay)
        if tm:
            w.append(TeachingAssignment.term == tm)
        return and_(*w)

    ta_base_where = [
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.teacher_id.in_(teacher_ids),
    ]
    ta_stmt = select(TeachingAssignment, Class, Subject).join(
        Class, TeachingAssignment.class_id == Class.id,
    ).join(Subject, TeachingAssignment.subject_id == Subject.id).where(
        _ta_where(ta_base_where, academic_year, term),
        Class.academic_year == academic_year,
        Class.term == term,
    )
    tas: dict[int, list[tuple[TeachingAssignment, Class, Subject]]] = defaultdict(list)
    teacher_class_ids: dict[int, set[int]] = defaultdict(set)
    ta_results = (await session.execute(ta_stmt)).all()
    for ta, cls, subj in ta_results:
        tas[ta.teacher_id].append((ta, cls, subj))
        teacher_class_ids[ta.teacher_id].add(cls.id)

    # 4b) TeachingClass —— 走班教学班任教关系（选科走班课表模式的课时来源）
    walk_classes: dict[int, list[TeachingClass]] = defaultdict(list)
    if teacher_ids:
        walk_stmt = select(TeachingClass).where(
            TeachingClass.tenant_id == tenant_id,
            TeachingClass.teacher_id.in_(teacher_ids),
            TeachingClass.academic_year == academic_year,
            TeachingClass.term == term,
        )
        for tc in (await session.execute(walk_stmt)).scalars().all():
            walk_classes[tc.teacher_id].append(tc)

    subject_rows = (await session.execute(select(Subject))).scalars().all()
    subject_name_by_id: dict[int, str] = {s.id: s.name for s in subject_rows}

    # 5) Schedule 已排课时 —— 同样严格按学年、学期统计
    scheduled_counts: dict[int, float] = defaultdict(float)
    if teacher_ids:
        sched_base = [Schedule.tenant_id == tenant_id, Schedule.teacher_id.in_(teacher_ids)]
        sched_where = list(sched_base)
        if academic_year:
            sched_where.append(Schedule.academic_year == academic_year)
        sched_where.append(Schedule.term == term)
        sched_stmt = select(Schedule.teacher_id, _SCHEDULE_UNIT).where(
            and_(*sched_where)
        ).group_by(Schedule.teacher_id)
        exact_counts: dict[int, float] = {}
        for tid, cnt in (await session.execute(sched_stmt)).fetchall():
            if tid is None:
                continue
            exact_counts[tid] = float(cnt or 0)
        for tid in teacher_ids:
            scheduled_counts[tid] = exact_counts.get(tid, 0)

    # 5b) TeachingClassSchedule 已排课时 —— 走班课表每行记 1 节（无单双周维度）
    walk_sched_counts: dict[int, float] = defaultdict(float)
    if teacher_ids:
        ws_stmt = select(TeachingClassSchedule.teacher_id, func.count()).where(
            TeachingClassSchedule.tenant_id == tenant_id,
            TeachingClassSchedule.teacher_id.in_(teacher_ids),
            TeachingClassSchedule.academic_year == academic_year,
            TeachingClassSchedule.term == term,
        ).group_by(TeachingClassSchedule.teacher_id)
        for tid, cnt in (await session.execute(ws_stmt)).fetchall():
            if tid is not None:
                walk_sched_counts[tid] = float(cnt or 0)

    plan_stmt = select(CourseHourPlan).where(CourseHourPlan.tenant_id == tenant_id)
    if academic_year:
        plan_stmt = plan_stmt.where(CourseHourPlan.academic_year == academic_year)
    if term:
        plan_stmt = plan_stmt.where(CourseHourPlan.term == term)
    hour_plans = list((await session.execute(plan_stmt)).scalars().all())
    plan_hours_by_scope: dict[tuple[int, int], float] = defaultdict(float)
    for plan in hour_plans:
        plan_hours_by_scope[(plan.class_id, plan.subject_id)] += _plan_equivalent_weekly(plan)

    # 6) 组织并应用筛选
    rows: list[dict[str, Any]] = []
    for t in teachers:
        if subject_id is not None and not any(subj.id == subject_id for _, _, subj in tas[t.id]) \
                and not any(tc.subject_id == subject_id for tc in walk_classes[t.id]):
            continue
        is_ht = t.id in head_teacher_ids
        # 仅班主任筛选
        if only_head_teacher and not is_ht:
            continue
        # grade_id => 班主任属于该年级
        if grade_id is not None and t.id not in head_teacher_ids_by_grade:
            # 若任课老师也按任教班级的 grade_id 筛
            ta_grade_match = any(class_map[ta.class_id].grade_id == grade_id for ta, _, _ in tas[t.id] if ta.class_id in class_map)
            if not ta_grade_match:
                # 组织任命匹配年级部
                appt_match = any(o.id in cohort_org_ids for _, o in staff_orgs[t.id])
                if not appt_match:
                    continue
        if cohort_entry_year is not None and not grade_id:
            # 按届别（组织任命或任教班级年级名含届别）
            appt_match = any(o.id in cohort_org_ids for _, o in staff_orgs[t.id])
            if not appt_match:
                # 任教班级匹配：Class.name 前缀是否等于 cohort_entry_year 对应届别标签
                rows_keep = False
                for _, cls, _ in tas[t.id]:
                    for _, o in staff_orgs.get(t.id, []):
                        if o.cohort_label == str(cohort_entry_year):
                            rows_keep = True
                            break
                # 额外根据班级名匹配届别（class name 含 "高一"/"高二"/"高三"）
                if not rows_keep:
                    cohort_to_grade_prefix: dict[str, str] = {}
                    if cohort_entry_year is not None:
                        # 对比班级头两个字 vs 当前届别推算
                        pass
                # 简化：只要 appointment 有对应cohort org 或 teaching class 绑定到对应grade（由grade_id逻辑已覆盖）
        # 职务标签
        position_tags = []
        for appt, org in staff_orgs[t.id]:
            label = _position_label(appt.position_code)
            position_tags.append({
                "organization_unit_id": org.id,
                "organization_name": org.name,
                "position_code": appt.position_code,
                "display_text": f"{org.name}·{label}",
            })

        # 任教班级汇总（行政班 + 走班教学班）
        teaching_classes = []
        weekly_total = 0.0
        for ta, cls, subj in tas[t.id]:
            scope = (ta.class_id, ta.subject_id)
            if scope in plan_hours_by_scope:
                periods = plan_hours_by_scope[scope]
            else:
                periods = float(ta.weekly_periods or 0)
            weekly_total += periods
            teaching_classes.append({
                "class_id": cls.id,
                "class_name": cls.name,
                "subject_id": subj.id,
                "subject_name": subj.name,
                "weekly_periods": periods,
                "kind": "admin",
            })
        for tc in walk_classes[t.id]:
            periods = float(tc.weekly_periods or 0)
            weekly_total += periods
            teaching_classes.append({
                "class_id": tc.id,
                "class_name": tc.name,
                "subject_id": tc.subject_id,
                "subject_name": subject_name_by_id.get(tc.subject_id, "未知学科"),
                "weekly_periods": periods,
                "kind": "walk",
            })
        scheduled = round(scheduled_counts.get(t.id, 0) + walk_sched_counts.get(t.id, 0), 1)
        ratio = 0.0
        if weekly_total > 0:
            ratio = round(min(scheduled / weekly_total, 1.0), 3)
        rows.append({
            "teacher_id": t.id,
            "name": t.name,
            "phone": t.phone,
            "is_head_teacher": is_ht,
            "head_teacher_classes": [class_map[cid].name for cid in sorted(class_map.keys()) if class_map[cid].head_teacher_id == t.id],
            "position_tags": position_tags,
            "teaching_classes": teaching_classes,
            "total_weekly_periods": round(weekly_total, 1),
            "scheduled_lessons_count": scheduled,
            "schedule_ratio": ratio,
        })

    # 排序：班主任优先，然后按总课时从大到小
    rows.sort(key=lambda r: (0 if r["is_head_teacher"] else 1, -r["total_weekly_periods"], r["name"]))

    # ------------------------------------------------------------------
    # 班级视角汇总：目标 = 课时管理 CourseHourPlan 折合周课时之和
    # 已排 = Schedule 折合周课时（单/双周各 0.5）
    # ------------------------------------------------------------------
    all_classes = list(class_map.values())
    # 1a) grade_id 过滤
    if grade_id is not None:
        all_classes = [c for c in all_classes if c.grade_id == grade_id]
    # 1b) cohort_entry_year 过滤：通过 OrganizationUnit.cohort_label 找到年级部，再用班级名前缀匹配
    if cohort_entry_year is not None:
        cohort_org_names_stmt = select(OrganizationUnit.name).where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.unit_type.in_(["grade", "cohort", "grade_group"]),
            OrganizationUnit.cohort_label == str(cohort_entry_year),
            OrganizationUnit.status == "active",
        )
        cohort_org_names = [r for r, in (await session.execute(cohort_org_names_stmt)).fetchall()]
        # 从年级部名中抽取"高一"/"高二"等前缀（去掉"届/年级/部"这些字）
        grade_prefixes: set[str] = set()
        for nm in cohort_org_names:
            for i in range(len(nm)):
                if i + 2 <= len(nm):
                    chunk = nm[i:i + 2]
                    if chunk in {"高一", "高二", "高三", "初一", "初二", "初三", "小一", "小二", "小三", "小四", "小五", "小六"}:
                        grade_prefixes.add(chunk)
                        break
        if grade_prefixes:
            # 班级名称可能带有校区前缀，例如“崇仁一中 · 高一（1）班”，
            # 年级标识不一定位于字符串开头，因此使用包含匹配。
            all_classes = [c for c in all_classes if any(p in c.name for p in grade_prefixes)]
        # else: 没有找到对应届别-年级的映射，不额外缩减（保持当前 grade_id 过滤后的集合）

    filtered_class_ids: set[int] = {c.id for c in all_classes}
    class_count = len(filtered_class_ids)
    scoped_plans = [p for p in hour_plans if p.class_id in filtered_class_ids]
    if scoped_plans:
        class_weekly_target = round(sum(_plan_equivalent_weekly(p) for p in scoped_plans), 1)
    else:
        grid = await _load_grid_config(session, tenant_id, academic_year or "", term)
        slots_each = _grid_slots_per_class(grid)
        class_weekly_target = round(class_count * slots_each, 1) if slots_each else class_count * 30

    class_scheduled_count = 0.0
    if filtered_class_ids:
        sched_where = [
            Schedule.tenant_id == tenant_id,
            Schedule.class_id.in_(list(filtered_class_ids)),
            Schedule.term == term,
        ]
        if academic_year:
            sched_where.append(Schedule.academic_year == academic_year)
        exact_val = (await session.execute(
            select(_SCHEDULE_UNIT).where(and_(*sched_where))
        )).scalar()
        class_scheduled_count = float(exact_val or 0)

    completion = 0.0
    if class_weekly_target > 0:
        completion = min(100.0, round(class_scheduled_count / class_weekly_target * 100, 1))

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "defaults": {
                "entry_year": cohort_entry_year,
                "academic_year": academic_year,
                "term": term,
            },
            "items": rows,
            "total": len(rows),
            # —— 班级视角汇总（新增） ——
            "class_summary": {
                "class_count": class_count,
                "weekly_target": class_weekly_target,
                "scheduled_lessons": round(class_scheduled_count, 1),
                "completion_ratio": completion,
            },
        },
    }


# ---------------------------------------------------------------------------
# 教师个人周课表
# ---------------------------------------------------------------------------


@router.get("/{teacher_id}/weekly-schedule", summary="查询教师当周课表")
async def teacher_weekly_schedule(
    teacher_id: int,
    academic_year: str | None = Query(default=None, description="学年，默认取配置"),
    term: str | None = Query(default=None, pattern="^[12]$"),
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
    user=Depends(get_current_user),
):
    defaults = await _defaults(session, tenant_id)
    term = term or defaults["term"]
    fallback_used = False
    if not academic_year:
        academic_year = defaults["academic_year"]

    # ---- 1) 先按配置/入参的 学年学期 精确匹配 ----
    where_exact = [Schedule.tenant_id == tenant_id, Schedule.teacher_id == teacher_id]
    if academic_year:
        where_exact.append(Schedule.academic_year == academic_year)
    if term:
        where_exact.append(Schedule.term == term)
    exact_stmt = select(Schedule).where(and_(*where_exact)).order_by(
        Schedule.weekday, Schedule.period
    )
    items = list((await session.execute(exact_stmt)).scalars().all())

    teachers = list((await session.execute(select(User).where(User.id == teacher_id))).scalars().all())
    subjects = list((await session.execute(select(Subject))).scalars().all())
    class_stmt = select(Class).where(Class.tenant_id == tenant_id)
    if academic_year:
        class_stmt = class_stmt.where(Class.academic_year == academic_year)
    if term:
        class_stmt = class_stmt.where(Class.term == term)
    classes = list((await session.execute(class_stmt)).scalars().all())
    tname = {t.id: t.name for t in teachers}
    sname = {s.id: s.name for s in subjects}
    cname = {c.id: c.name for c in classes}
    data = []
    for it in items:
        d = it.model_dump()
        d.update(
            teacher_name=tname.get(it.teacher_id, "未指定"),
            subject_name=sname.get(it.subject_id, "未知学科"),
            class_name=cname.get(it.class_id, "未知班级"),
            kind="admin",
        )
        data.append(d)
    # 走班教学班课表（选科走班模式：课表存于 TeachingClassSchedule，不在 Schedule）
    walk_stmt = select(TeachingClassSchedule, TeachingClass).join(
        TeachingClass, TeachingClassSchedule.teaching_class_id == TeachingClass.id,
    ).where(
        TeachingClassSchedule.tenant_id == tenant_id,
        TeachingClassSchedule.teacher_id == teacher_id,
        TeachingClassSchedule.academic_year == academic_year,
        TeachingClassSchedule.term == term,
    )
    for row, tc in (await session.execute(walk_stmt)).all():
        d = row.model_dump()
        d.update(
            class_id=tc.id,
            week_parity="all",
            teacher_name=tname.get(row.teacher_id, "未指定"),
            subject_name=sname.get(row.subject_id, "未知学科"),
            class_name=tc.name,
            kind="walk",
        )
        data.append(d)
    data.sort(key=lambda item: (item.get("weekday", 0), item.get("period", 0)))
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "teacher_name": tname.get(teacher_id),
            "items": data,
            "fallback_used": fallback_used,
            "applied": {
                "academic_year": academic_year,
                "term": term,
            },
        },
    }
