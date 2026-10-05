"""新手引导：教务排课准备度清单，状态全部来自本校真实数据。

每步的完成判定与详情文案在这里统一计算，前端只负责展示与跳转。
步骤顺序即推荐操作顺序（学年学期 → 教师人员 → 空间 → 资源分配 → 班级划分 → 课位 → 课时 → 任教 → 规则 → 生成）。
跳过标记存 TenantConfig（学校级配置，沿用网格/规则目录的存储惯例），不建新表。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.facility import Building, Campus, ResourceAllocationRule, Room, RoomCohortAllocation
from app.models.org import Class, CourseHourPlan, Grade, Schedule, TeachingAssignment, TenantConfig, User
from app.models.rbac import Role, UserRole
from app.models.enums import BaseUserRole, UserStatus
from app.services.org.cohort import cohort_labels_match, expected_cohort_label
from app.services.org.staff_roles import get_staff_role_codes

router = APIRouter(prefix="/onboarding", tags=["新手引导"])

VERSION_HISTORY_KEY = "scheduling_version_history"
GUIDE_CONFIG_KEY = "onboarding_guide"


def _dismissed_from(raw: object) -> bool:
    return bool(isinstance(raw, dict) and raw.get("dismissed"))


def teaching_staff_count_query(tenant_id: int):
    """基础角色 teacher 也用于普通人员；仅统计本校有任教角色的可用账号。"""
    return (
        select(func.count(distinct(User.id))).select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            User.tenant_id == tenant_id,
            User.role == BaseUserRole.teacher,
            User.status == UserStatus.active,
            User.frozen.is_(False),
            Role.tenant_id == tenant_id,
            Role.code == "subject_teacher",
        )
    )


async def _set_dismissed(session: AsyncSession, tenant_id: int, user_id: int, value: bool) -> None:
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == GUIDE_CONFIG_KEY,
    ).with_for_update())).scalars().first()
    payload = {"dismissed": value, "updated_at": datetime.utcnow().isoformat() + "Z"}
    if row is None:
        session.add(TenantConfig(
            tenant_id=tenant_id, config_key=GUIDE_CONFIG_KEY,
            config_value=payload, updated_by=user_id,
        ))
    else:
        row.config_value = payload
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()
    await session.commit()


@router.post("/dismiss", summary="跳过新手引导（全校生效）")
async def dismiss_onboarding(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _set_dismissed(session, tenant_id, user.id, True)
    return {"code": 0, "message": "ok", "data": {"dismissed": True}}


@router.post("/reopen", summary="重新开启新手引导（全校生效）")
async def reopen_onboarding(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _set_dismissed(session, tenant_id, user.id, False)
    return {"code": 0, "message": "ok", "data": {"dismissed": False}}


def evaluate_steps(
    *,
    year: str | None,
    term: str,
    campus_count: int,
    building_count: int,
    room_count: int,
    allocation_rule_count: int,
    allocated_room_count: int,
    resource_assigned_class_count: int,
    grid_configured: bool,
    grid_line: str,
    class_total: int,
    hour_classes: int,
    teacher_count: int,
    asg_class_count: int,
    rule_group_count: int,
    enabled_rules: int,
    version_count: int,
    staff_count: int = 0,
    schedule_count: int = 0,
    history_year: str | None = None,
    history_hour_classes: int = 0,
) -> list[dict]:
    if campus_count == 0:
        space_detail = "先创建校区，再逐级新增楼宇和场室"
    elif building_count == 0:
        space_detail = f"已有 {campus_count} 个校区，还没有楼宇；请选择校区后新增楼宇"
    elif room_count == 0:
        space_detail = f"已有 {campus_count} 个校区、{building_count} 栋楼宇，还没有可排课场室；请新增场室或核对现有场室状态"
    else:
        space_detail = f"已有 {campus_count} 个校区、{building_count} 栋楼宇、{room_count} 间可排课场室"

    if not year:
        allocation_detail = "先设置当前学年学期，再按届别分配场室"
    elif room_count == 0:
        allocation_detail = "先建好场室，再创建届别资源分配规则"
    elif allocated_room_count == 0:
        allocation_detail = "当前学期还没有教室分配给届别，请创建规则、预览并执行分配"
    else:
        allocation_detail = f"当前学期 {allocation_rule_count} 条规则已分配 {allocated_room_count} 间教室"

    if not year:
        class_planning_detail = "先设置当前学年学期，再检查届别资源和行政班"
    elif allocated_room_count == 0:
        class_planning_detail = "先完成届别资源分配，班级划分只使用已分配的教室"
    elif class_total == 0:
        class_planning_detail = f"已有 {allocated_room_count} 间可用教室，尚未据此生成行政班"
    else:
        class_planning_detail = f"{resource_assigned_class_count}/{class_total} 个行政班已绑定当前学期分配的教室"

    return [
        {
            "key": "year",
            "title": "核对学年学期",
            "done": bool(year),
            "detail": f"{year} 学年 · 第 {term} 学期" if year else "还没有设置当前学年学期",
            "path": "/settings",
        },
        {
            "key": "personnel",
            "title": "准备教师人员",
            "done": staff_count > 0,
            "detail": (
                f"已有 {staff_count} 位启用且未冻结的教师；任教覆盖将在后续单独核对"
                if staff_count else "还没有可用于任教的教师，请到人员账号添加教师并启用账号"
            ),
            "path": "/staff",
        },
        {
            "key": "space",
            "title": "建全空间层级",
            "done": campus_count > 0 and building_count > 0 and room_count > 0,
            "detail": space_detail,
            "path": "/campus-buildings?tab=resources",
        },
        {
            "key": "allocation",
            "title": "分配届别资源",
            "done": allocation_rule_count > 0 and allocated_room_count > 0,
            "detail": allocation_detail,
            "path": "/campus-buildings?tab=allocation",
        },
        {
            "key": "class_planning",
            "title": "完成班级划分",
            "done": class_total > 0 and resource_assigned_class_count == class_total,
            "detail": class_planning_detail,
            "path": "/campus-buildings?tab=class-planning",
        },
        {
            "key": "grid",
            "title": "保存课位结构",
            "done": bool(grid_configured),
            "detail": grid_line if grid_configured else "确认一周几天、每天几节、有无晚自习",
            "path": "/scheduling?tab=slots",
        },
        {
            "key": "hours",
            "title": "填写班级课时",
            "done": class_total > 0 and hour_classes >= class_total,
            "detail": (
                "先设置当前学年学期，再填写班级课时"
                if not year
                else "还没有行政班，请先到空间资源的“班级划分”生成班级"
                if class_total == 0
                else (
                    f"检测到 {history_year} 学年已有 {history_hour_classes} 个班的课时，新学期请参考原结构填写"
                    if hour_classes == 0 and history_year
                    else f"{hour_classes}/{class_total} 个班已填周节数"
                )
            ),
            "path": "/scheduling?tab=hours",
        },
        {
            "key": "assignments",
            "title": "建立任教关系",
            "done": class_total > 0 and teacher_count > 0 and asg_class_count >= class_total,
            "detail": (
                f"{teacher_count} 位教师覆盖 {asg_class_count} 个班" if teacher_count
                else (
                    f"检测到 {history_year} 学年的任教关系，新学期请重新对老师" if history_year
                    else "还没有教师和班的对应关系"
                )
            ),
            "path": "/scheduling?tab=assignments",
        },
        {
            "key": "rules",
            "title": "配置排课规则",
            "done": enabled_rules > 0,
            "detail": (
                f"{rule_group_count} 个规则组 · 启用 {enabled_rules} 条规则" if rule_group_count
                else "还没有规则组，可按模板添加禁排、连堂等"
            ),
            "path": "/scheduling?tab=rules",
        },
        {
            "key": "generate",
            "title": "生成第一张课表",
            "done": bool(year) and schedule_count > 0,
            "detail": (
                f"当前学期已有 {schedule_count} 个排课条目"
                + (f"、{version_count} 个可恢复历史版本" if version_count else "")
                if schedule_count else "当前学期尚无课表；在排课页生成后检查冲突"
            ),
            "path": "/scheduling",
        },
    ]


@router.get("/status", summary="新手引导进度（教务排课准备流程）")
async def onboarding_status(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    result = await load_onboarding_status(session, tenant_id)
    role_codes = await get_staff_role_codes(session, user.id) if user.role == BaseUserRole.teacher else set()
    if "head_teacher" in role_codes:
        source = {step["key"]: step for step in result["data"]["steps"]}
        result["data"]["audience"] = "head_teacher"
        result["data"]["steps"] = [
            {"key": "my_classes", "title": "查看我的班级", "done": source.get("class_planning", {}).get("done", False), "detail": "确认班级和学生范围", "path": "/teacher-classes"},
            {"key": "my_students", "title": "核对我的学生", "done": False, "detail": "查看本班学生名单与选科状态", "path": "/teacher-students"},
            {"key": "choice_review", "title": "审核学生选科", "done": False, "detail": "逐个核对或批量通过学生选科意愿", "path": "/teacher-students"},
            {"key": "class_schedule", "title": "查看班级课表", "done": source.get("generate", {}).get("done", False), "detail": "课表生成后检查本班上课安排", "path": "/teacher-courses"},
        ]
    elif "subject_teacher" in role_codes:
        source = {step["key"]: step for step in result["data"]["steps"]}
        result["data"]["audience"] = "subject_teacher"
        result["data"]["steps"] = [
            {"key": "my_courses", "title": "查看我的课程", "done": source.get("assignments", {}).get("done", False), "detail": "确认任教班级和学科", "path": "/teacher-courses"},
            {"key": "preparation", "title": "准备教学内容", "done": False, "detail": "进入备课页面整理教学资料", "path": "/teacher-preparation"},
            {"key": "schedule", "title": "查看我的课表", "done": source.get("generate", {}).get("done", False), "detail": "课表生成后核对上课时间与教室", "path": "/teacher-courses"},
            {"key": "grades", "title": "登记与查看成绩", "done": False, "detail": "从成绩页面管理授课班级成绩", "path": "/teacher-grades"},
        ]
    else:
        result["data"]["audience"] = "management"
    result["data"]["done_count"] = sum(1 for step in result["data"]["steps"] if step["done"])
    result["data"]["total"] = len(result["data"]["steps"])
    return result


async def load_onboarding_status(session: AsyncSession, tenant_id: int) -> dict:
    """供新手引导和助手共用的学校准备事实；无页面跳转或写入。"""
    from app.api.v1.scheduling import _load_grid_config, _load_rule_catalog
    from app.api.v1.teacher_profiles import _defaults

    defaults = await _defaults(session, tenant_id)
    year = defaults.get("academic_year") or ""
    term = str(defaults.get("term") or "1")

    grid_line = "网格未配置"
    grid_configured = False
    if year:
        grid = await _load_grid_config(session, tenant_id, year, term)
        grid_configured = bool(grid.get("configured"))
        if grid_configured:
            grid_line = (
                f"{grid.get('days')} 天 × {grid.get('periods_per_day')} 节"
                + ("，含晚自习" if grid.get("enable_evening") else "")
            )

    class_rows = (await session.execute(
        select(Class.id, Class.home_room_id, Class.cohort_label, Grade.level)
        .join(Grade, Grade.id == Class.grade_id)
        .where(Class.tenant_id == tenant_id)
    )).all()
    current_classes = [
        row for row in class_rows
        if year and cohort_labels_match(row.cohort_label, expected_cohort_label(year, row.level))
    ]
    current_class_ids = {row.id for row in current_classes}
    class_total = len(current_classes)
    schedule_count = (await session.execute(
        select(func.count()).select_from(Schedule).where(
            Schedule.tenant_id == tenant_id,
            Schedule.academic_year == year,
            Schedule.term == term,
            Schedule.class_id.in_(current_class_ids),
        )
    )).scalar_one() if current_class_ids else 0
    staff_count = (await session.execute(teaching_staff_count_query(tenant_id))).scalar_one()
    campus_count = (await session.execute(
        select(func.count()).select_from(Campus).where(
            Campus.tenant_id == tenant_id, Campus.status == "active",
        )
    )).scalar_one()
    building_count = (await session.execute(
        select(func.count()).select_from(Building).where(Building.tenant_id == tenant_id)
    )).scalar_one()
    room_count = (await session.execute(
        select(func.count()).select_from(Room)
        .join(Building, Building.id == Room.building_id)
        .join(Campus, Campus.id == Building.campus_id)
        .where(
            Room.tenant_id == tenant_id,
            Room.is_schedulable.is_(True),
            Room.status == "available",
            Campus.tenant_id == tenant_id,
            Campus.status == "active",
        )
    )).scalar_one()
    allocation_rule_count = 0
    allocated_room_ids: set[int] = set()
    resource_assigned_class_count = 0
    if year:
        allocation_rule_count = (await session.execute(
            select(func.count()).select_from(ResourceAllocationRule).where(
                ResourceAllocationRule.tenant_id == tenant_id,
                ResourceAllocationRule.academic_year == year,
                ResourceAllocationRule.term == term,
                ResourceAllocationRule.status == "active",
            )
        )).scalar_one()
        allocated_room_ids = set((await session.execute(
            select(distinct(RoomCohortAllocation.room_id))
            .join(Room, Room.id == RoomCohortAllocation.room_id)
            .where(
                RoomCohortAllocation.tenant_id == tenant_id,
                RoomCohortAllocation.academic_year == year,
                RoomCohortAllocation.term == term,
                RoomCohortAllocation.status == "active",
                Room.tenant_id == tenant_id,
                Room.is_schedulable.is_(True),
                Room.status == "available",
            )
        )).scalars().all())
        resource_assigned_class_count = sum(
            row.home_room_id in allocated_room_ids for row in current_classes
        )
    hour_classes = 0
    asg_teacher_ids: set[int] = set()
    asg_class_ids: set[int] = set()
    if year:
        hour_classes = (await session.execute(
            select(func.count(distinct(CourseHourPlan.class_id))).where(
                CourseHourPlan.tenant_id == tenant_id,
                CourseHourPlan.academic_year == year,
                CourseHourPlan.term == term,
                CourseHourPlan.class_id.in_(current_class_ids) if current_class_ids else False,
                CourseHourPlan.weekday_periods > 0,
            )
        )).scalar_one()
        for tid, cid in (await session.execute(
            select(TeachingAssignment.teacher_id, TeachingAssignment.class_id)
            .join(User, User.id == TeachingAssignment.teacher_id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                TeachingAssignment.tenant_id == tenant_id,
                TeachingAssignment.academic_year == year,
                TeachingAssignment.term == term,
                TeachingAssignment.class_id.in_(current_class_ids),
                User.tenant_id == tenant_id,
                User.role == BaseUserRole.teacher,
                User.status == UserStatus.active,
                User.frozen.is_(False),
                Role.tenant_id == tenant_id,
                Role.code == "subject_teacher",
            )
        )).all():
            if tid is not None:
                asg_teacher_ids.add(tid)
            if cid is not None:
                asg_class_ids.add(cid)

    groups: list = []
    if year:
        groups, _active_id = await _load_rule_catalog(session, tenant_id, year, term)
    enabled_rules = sum(1 for g in groups for r in g.rules if r.enabled)

    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == VERSION_HISTORY_KEY,
    ))).scalars().first()
    raw = row.config_value if row else None
    if isinstance(raw, list):
        history = [v for v in raw if isinstance(v, dict)]
    elif isinstance(raw, dict) and isinstance(raw.get("versions"), list):
        history = [v for v in raw["versions"] if isinstance(v, dict)]
    else:
        history = []

    # 往年课时（历史数据检测）：取最近一个有课时数据的非当前学年
    hist = (await session.execute(
        select(CourseHourPlan.academic_year, func.count(distinct(CourseHourPlan.class_id)))
        .where(
            CourseHourPlan.tenant_id == tenant_id,
            CourseHourPlan.academic_year != (year or ""),
            CourseHourPlan.weekday_periods > 0,
        )
        .group_by(CourseHourPlan.academic_year)
        .order_by(CourseHourPlan.academic_year.desc())
        .limit(1)
    )).first()
    history_year, history_hour_classes = (hist[0], int(hist[1])) if hist else (None, 0)

    guide_row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == GUIDE_CONFIG_KEY,
    ))).scalars().first()
    dismissed = _dismissed_from(guide_row.config_value if guide_row else None)

    steps = evaluate_steps(
        year=year or None,
        term=term,
        campus_count=int(campus_count or 0),
        building_count=int(building_count or 0),
        room_count=int(room_count or 0),
        allocation_rule_count=int(allocation_rule_count or 0),
        allocated_room_count=len(allocated_room_ids),
        resource_assigned_class_count=int(resource_assigned_class_count or 0),
        grid_configured=grid_configured,
        grid_line=grid_line,
        class_total=int(class_total or 0),
        hour_classes=int(hour_classes or 0),
        teacher_count=len(asg_teacher_ids),
        asg_class_count=len(asg_class_ids),
        rule_group_count=len(groups),
        enabled_rules=enabled_rules,
        version_count=sum(
            1 for version in history
            if version.get("academic_year") == year and str(version.get("term")) == str(term)
        ),
        staff_count=int(staff_count or 0),
        schedule_count=int(schedule_count or 0),
        history_year=history_year,
        history_hour_classes=history_hour_classes,
    )
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "steps": steps,
            "done_count": sum(1 for s in steps if s["done"]),
            "total": len(steps),
            "history_year": history_year,
            "dismissed": dismissed,
        },
    }
