"""领域枚举 - 集中定义各表使用的 enum 类型

SQLModel 中标注为 str+Enum 的字段会映射为 SQLAlchemy Enum 列。
集中于此避免跨域重复定义。
"""
from enum import Enum


class TenantType(str, Enum):
    """租户类型"""
    personal = "personal"      # 个人试用
    org = "org"                # 学校


class BaseUserRole(str, Enum):
    """用户基础角色（user.role 冗余列，细粒度走 RBAC user_role）"""
    director = "director"      # 教导主任/全局
    teacher = "teacher"        # 老师/本班


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class Gender(str, Enum):
    male = "male"
    female = "female"


class StudentStatus(str, Enum):
    studying = "studying"         # 在读
    leave = "leave"               # 休学
    transferred = "transferred"   # 转出


class CheckInStatus(str, Enum):
    none = "none"                 # 未报到
    checked = "checked"           # 已报到
    hand_confirmed = "hand_confirmed"   # 人工确认
    contacting = "contacting"     # 未联系上


class EnrollmentStatus(str, Enum):
    importing = "importing"       # 导入中
    partial = "partial"           # 部分成功
    finished = "finished"         # 完成


class SeatRule(str, Enum):
    roster = "roster"             # 按名册
    height = "height"
    grade = "grade"
    gender = "gender"
    snake = "snake"               # 蛇形
    random = "random"             # 随机
    score = "score"               # 按某场考试成绩总分
    manual = "manual"


class SeatLayout(str, Enum):
    normal = "normal"             # 逐行顺排（左→右）
    snake = "snake"               # 蛇形排列（相邻两行反向）


class SeatStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ExamType(str, Enum):
    weekly = "weekly"             # 周测
    monthly = "monthly"           # 月考
    midterm = "midterm"           # 期中
    final = "final"               # 期末
    mock = "mock"                 # 模拟


class ExamStatus(str, Enum):
    preparing = "preparing"       # 筹备
    ongoing = "ongoing"           # 进行中
    finished = "finished"         # 已结束
    archived = "archived"         # 已归档


class WeekParity(str, Enum):
    """课表项周次归属：普通模式恒为 all；单双周模式用 odd/even。"""
    all = "all"      # 每周都上
    odd = "odd"      # 单周
    even = "even"    # 双周


class EveningParity(str, Enum):
    """晚课 0.5 节的单双周：可指定，也可无规定由程序安排。"""
    all = "all"          # 1 节：单双周都上
    odd = "odd"          # 0.5 节：锁定单周
    even = "even"        # 0.5 节：锁定双周
    either = "either"    # 0.5 节：无规定，求解器任选单或双
