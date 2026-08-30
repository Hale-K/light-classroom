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


class CheckInMethod(str, Enum):
    scan = "scan"                 # 扫码报到
    manual = "manual"             # 人工补录
    phone = "phone"               # 电话确认


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


class DifficultyLevel(str, Enum):
    basic = "basic"               # 基础
    mid = "mid"                   # 中档
    advanced = "advanced"         # 拔高


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


class PaperStatus(str, Enum):
    building = "building"         # 建卷中
    finalized = "finalized"       # 已定稿
    grading = "grading"           # 阅卷中
    published = "published"       # 已发布


class ScanBatchStatus(str, Enum):
    uploaded = "uploaded"         # 已上传
    split = "split"               # 已切分
    assigned = "assigned"         # 已分配
    confirmed = "confirmed"       # 已确认


class SubmissionStatus(str, Enum):
    absent = "absent"             # 缺考
    scanned = "scanned"           # 已扫描
    grading = "grading"           # 打分中
    graded = "graded"             # 已打分
    published = "published"       # 已发布


class GradingMode(str, Enum):
    manual = "manual"             # 纯人工
    ocr = "ocr"                   # 客观题自动
    ai_pre = "ai_pre"             # AI 预批


class ConfirmStatus(str, Enum):
    pending = "pending"           # 待复核
    confirmed = "confirmed"       # 已确认
    changed = "changed"           # 有异议已改


class ProfileTier(str, Enum):
    weak = "weak"                 # 薄弱
    mid = "mid"                   # 中档
    excellent = "excellent"       # 优秀


class PlanType(str, Enum):
    weekly = "weekly"             # 周教学计划
    unit = "unit"                 # 单元计划
    pre_exam = "pre_exam"         # 考前复习计划
    suggestion = "suggestion"     # 教学建议


class PlanStatus(str, Enum):
    generated = "generated"
    referred = "referred"
    edited = "edited"


class PracticeStatus(str, Enum):
    generated = "generated"       # 生成
    reviewed = "reviewed"         # 已审核
    printed = "printed"           # 已打印
    returned = "returned"         # 已回流


class QuestionType(str, Enum):
    single = "single"             # 单选
    multi = "multi"               # 多选
    fill = "fill"                 # 填空
    short_answer = "short_answer" # 简答
    calc = "calc"                 # 计算
    essay = "essay"               # 作文


class SourceType(str, Enum):
    real = "real"                 # 真题
    mock = "mock"                 # 模拟
    tutoring = "tutoring"         # 教辅
    web = "web"                   # 网络
    self = "self"                 # 自编


class ExamNature(str, Enum):
    gaokao = "gaokao"             # 高考真题
    mock = "mock"                 # 模拟
    monthly = "monthly"
    midterm = "midterm"
    final = "final"
    weekly = "weekly"


class TopicCategory(str, Enum):
    politics = "politics"         # 时政
    tech = "tech"                 # 科技
    livelihood = "livelihood"     # 民生
    culture = "culture"           # 文化
    sports = "sports"             # 体育
    finance = "finance"           # 财经


class TrendDirection(str, Enum):
    up = "up"
    stable = "stable"
    down = "down"


class PredictionTaskStatus(str, Enum):
    queued = "queued"
    generating = "generating"
    generated = "generated"
    reviewed = "reviewed"
    published = "published"
    discarded = "discarded"


class PredictionItemStatus(str, Enum):
    pending = "pending"           # 待审核
    adopted = "adopted"           # 已采纳
    rejected = "rejected"         # 已驳回


class WeekParity(str, Enum):
    """课表项周次归属：普通模式恒为 all；单双周模式用 odd/even。"""
    all = "all"      # 每周都上
    odd = "odd"      # 单周
    even = "even"    # 双周
