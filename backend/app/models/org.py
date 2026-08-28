"""组织域模型
tenant / tenant_config / user / grade / class / student / subject /
teaching_assignment / knowledge_point / enrollment_batch / checkin_record /
schedule / seat_arrangement
"""
from datetime import date, datetime
from typing import Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, UniqueConstraint

from app.db.base import TimestampMixin, TenantMixin
from app.models.enums import (
    BaseUserRole, CheckInMethod, CheckInStatus, EnrollmentStatus,
    Gender, SeatLayout, SeatRule, SeatStatus, StudentStatus, TenantType, UserStatus,
)


class Tenant(SQLModel, table=True):
    """租户 = 学校"""
    __table_args__ = {"comment": "租户(学校)"}
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=32, unique=True, index=True, description="学校代码(业务标识)")
    name: str = Field(max_length=100, description="学校名称")
    type: TenantType = Field(default=TenantType.org)
    province: str = Field(default="全国通用", max_length=50, description="学校所在省份")
    gaokao_mode: str = Field(default="3+1+2", max_length=20, description="学校默认高考模式")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TenantConfig(SQLModel, table=True):
    """租户个性化配置（按校定制）"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "config_key", name="uq_tenantconfig_tenant_key"),
        {"comment": "租户个性化配置"},
    )
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(index=True)
    config_key: str = Field(max_length=50, description="配置键 school_name/logo/print_template...")
    config_value: dict | None = Field(default=None, sa_type=JSON, description="配置值(json)")
    updated_by: int | None = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class User(TimestampMixin, TenantMixin, SQLModel, table=True):
    """用户（老师/教导主任）"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone", name="uq_user_tenant_phone"),
        {"comment": "用户"},
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=50, description="姓名")
    phone: str = Field(max_length=20, index=True, description="登录账号")
    password_hash: str = Field(max_length=255)
    role: BaseUserRole = Field(default=BaseUserRole.teacher, description="基础角色")
    teacher_level: str | None = Field(default=None, max_length=30, description="教师职级")
    status: UserStatus = Field(default=UserStatus.active)


class OrganizationUnit(TimestampMixin, TenantMixin, SQLModel, table=True):
    """Persisted school organization node; the school itself is represented by Tenant."""
    __table_args__ = (
        UniqueConstraint("tenant_id", "parent_id", "name", name="uq_orgunit_parent_name"),
        {"comment": "学校组织机构"},
    )
    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(default=None, index=True)
    name: str = Field(max_length=100)
    unit_type: str = Field(default="department", max_length=30, index=True)
    grade_id: int | None = Field(default=None, index=True, foreign_key="grade.id", ondelete="RESTRICT", description="年级部对应的基础年级")
    academic_year: str | None = Field(default=None, max_length=20, index=True)
    cohort_label: str | None = Field(default=None, max_length=30, index=True)
    sort_order: int = Field(default=0)
    status: str = Field(default="active", max_length=20, index=True)


class StaffAppointment(TimestampMixin, TenantMixin, SQLModel, table=True):
    """Time-scoped appointment of a staff account to a position in an organization unit."""
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "organization_unit_id", "staff_id", "position_code", "academic_year",
            name="uq_staffappointment_scope",
        ),
        {"comment": "人员岗位任命"},
    )
    id: int | None = Field(default=None, primary_key=True)
    organization_unit_id: int = Field(index=True)
    staff_id: int = Field(index=True)
    position_code: str = Field(max_length=40, index=True)
    academic_year: str | None = Field(default=None, max_length=20, index=True)
    status: str = Field(default="active", max_length=20, index=True)
    appointed_by: int | None = Field(default=None, index=True)


class Grade(TenantMixin, SQLModel, table=True):
    """年级"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_grade_tenant_name"),
        {"comment": "年级"},
    )
    id: int | None = Field(default=None, primary_key=True)
    campus_id: int | None = Field(default=None, index=True)
    name: str = Field(max_length=50, description="如 高一年级")
    level: int = Field(description="1/2/3 排序用")


class Class(TenantMixin, SQLModel, table=True):
    """班级"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "grade_id", "cohort_label", "name", name="uq_class_grade_cohort_name"),
        {"comment": "班级"},
    )
    id: int | None = Field(default=None, primary_key=True)
    grade_id: int = Field(index=True)
    campus_id: int | None = Field(default=None, index=True)
    home_room_id: int | None = Field(default=None, index=True)
    class_type: str = Field(default="regular", max_length=30, index=True, description="尖子班/重点班/普通班等")
    planned_student_count: int | None = Field(default=None, ge=1, le=45)
    name: str = Field(max_length=50, description="如 高一(1)班")
    cohort_label: str | None = Field(default=None, max_length=30, index=True, description="届（入学年，如 2026）；同一届的班级随学年升级整体改挂年级")
    head_teacher_id: int | None = Field(default=None, description="班主任(本班×全学科视角)")
    deputy_head_teacher_id: int | None = Field(default=None, description="副班主任")


class Student(TimestampMixin, TenantMixin, SQLModel, table=True):
    """学生"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_no", name="uq_student_tenant_no"),
        {"comment": "学生"},
    )
    id: int | None = Field(default=None, primary_key=True)
    campus_id: int | None = Field(default=None, index=True, description="所属校区")
    grade_id: int | None = Field(default=None, index=True, description="所属年级；可先定年级后分班")
    class_id: int | None = Field(default=None, index=True, description="行政班；空值表示待分班")
    name: str = Field(max_length=50)
    gender: Gender = Field(index=True)
    id_card: str | None = Field(default=None, max_length=32, description="身份证号(加密)")
    birth_date: date | None = Field(default=None)
    parent_phone: str | None = Field(default=None, max_length=32, description="家长手机(加密)")
    height_cm: float | None = Field(default=None, ge=80, le=250, description="身高（厘米）")
    student_no: str | None = Field(default=None, max_length=32, index=True, description="学号")
    roster_order: int = Field(default=0, description="名册顺序号(扫描按序分配依据)")
    check_in_status: CheckInStatus = Field(default=CheckInStatus.none)
    checked_in_at: datetime | None = Field(default=None)
    status: StudentStatus = Field(default=StudentStatus.studying)


class StudentGradeMembership(TimestampMixin, TenantMixin, SQLModel, table=True):
    """学生与届别年级部的快照关系。

    班级只是行政分班结果；该表保存学生在某学年归属的年级部，供跨班级
    查询、历史追溯和组织节点删除保护使用。
    """
    __tablename__ = "studentgrademembership"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "academic_year",
            name="uq_studentgrademembership_student_year",
        ),
        {"comment": "学生年级部关联快照"},
    )
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True, foreign_key="student.id", ondelete="RESTRICT")
    grade_id: int = Field(index=True, foreign_key="grade.id", ondelete="RESTRICT")
    grade_unit_id: int = Field(index=True, foreign_key="organizationunit.id", ondelete="RESTRICT")
    academic_year: str = Field(max_length=20, index=True, description="学年快照")
    cohort_label: str | None = Field(default=None, max_length=30, index=True, description="届别快照")
    status: str = Field(default="active", max_length=20, index=True)


class Subject(SQLModel, table=True):
    """学科（全局字典）"""
    __table_args__ = {"comment": "学科字典"}
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=20, unique=True, description="语文/数学/英语/物理/化学/生物/政治/历史/地理")


class TeachingAssignment(TenantMixin, SQLModel, table=True):
    """任教关系（一师多班，一行一班级）"""
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "class_id", "subject_id", "academic_year", "term",
            name="uq_teachingassignment_scope",
        ),
        {"comment": "任教关系"},
    )
    id: int | None = Field(default=None, primary_key=True)
    teacher_id: int = Field(index=True, foreign_key="user.id", ondelete="RESTRICT")
    subject_id: int = Field(index=True, foreign_key="subject.id", ondelete="RESTRICT")
    class_id: int = Field(index=True, foreign_key="class.id", ondelete="RESTRICT")
    academic_year: str = Field(max_length=20, description="如 2026-2027")
    term: str = Field(default="1", max_length=20)
    weekly_periods: int = Field(default=4, ge=1, le=20)
    room: str | None = Field(default=None, max_length=50)


class KnowledgePoint(SQLModel, table=True):
    """知识点（树形，九科×年级预置）"""
    __table_args__ = {"comment": "知识点"}
    id: int | None = Field(default=None, primary_key=True)
    subject_id: int = Field(index=True)
    grade_level: int = Field(default=0, description="对应年级层")
    parent_id: int | None = Field(default=None, index=True, description="父节点：章节→小节")
    name: str = Field(max_length=100)
    code: str = Field(max_length=50, index=True, description="唯一编码")


class EnrollmentBatch(TimestampMixin, TenantMixin, SQLModel, table=True):
    """新生导入批次（报名录入）"""
    __table_args__ = {"comment": "新生导入批次"}
    id: int | None = Field(default=None, primary_key=True)
    source: str | None = Field(default=None, max_length=255, description="来源(教育局中招导出)")
    file_name: str | None = Field(default=None, max_length=255)
    total_count: int = Field(default=0)
    success_count: int = Field(default=0)
    fail_count: int = Field(default=0)
    errors: dict | None = Field(default=None, sa_type=JSON, description="错误明细(行号+原因)")
    status: EnrollmentStatus = Field(default=EnrollmentStatus.importing)
    created_by: int | None = Field(default=None)


class CheckinRecord(TimestampMixin, TenantMixin, SQLModel, table=True):
    """报到记录（校门口扫码）"""
    __table_args__ = {"comment": "报到记录"}
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True)
    batch: str | None = Field(default=None, max_length=50, description="报到批次/日期")
    method: CheckInMethod = Field(default=CheckInMethod.scan)
    verify_fields: dict | None = Field(default=None, sa_type=JSON, description="核验字段")
    verified_at: datetime | None = Field(default=None)
    created_by: int | None = Field(default=None)


class Schedule(TimestampMixin, TenantMixin, SQLModel, table=True):
    """行政班课表项"""
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "academic_year", "term", "class_id", "weekday", "period",
            name="uq_schedule_class_slot",
        ),
        {"comment": "课表项", "sqlite_autoincrement": True},
    )
    id: int | None = Field(default=None, primary_key=True)
    class_id: int = Field(index=True, foreign_key="class.id", ondelete="RESTRICT")
    weekday: int = Field(description="星期 1-7")
    period: int = Field(description="节次 1-N")
    subject_id: int = Field(default=None, foreign_key="subject.id", ondelete="RESTRICT")
    teacher_id: int | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    room: str | None = Field(default=None, max_length=50)
    academic_year: str = Field(max_length=20)
    term: str = Field(default=None, max_length=20)


class SeatArrangement(TimestampMixin, TenantMixin, SQLModel, table=True):
    """排座位（班主任）"""
    __table_args__ = {"comment": "排座位"}
    id: int | None = Field(default=None, primary_key=True)
    class_id: int = Field(index=True)
    rows: int = Field(default=0)
    cols: int = Field(default=0)
    rule: SeatRule = Field(default=SeatRule.manual)
    layout: SeatLayout = Field(default=SeatLayout.normal)
    student_map: dict | None = Field(default=None, sa_type=JSON, description="座位→学生映射")
    effective_from: date | None = Field(default=None)
    effective_to: date | None = Field(default=None)
    status: SeatStatus = Field(default=SeatStatus.draft)
    created_by: int | None = Field(default=None)
