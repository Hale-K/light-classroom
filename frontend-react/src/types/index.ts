/**
 * 轻课堂 · 共享类型 / 枚举 / 常量（React 版内聚，与后端 FastAPI 契约对齐）
 */

/** 后端统一响应结构：成功 code=0 */
export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

/** 用户 */
export interface UserInfo {
  id: number;
  name: string;
  phone?: string;
  role?: string;
  roles?: string[];
  school_code?: string;
}

export type StaffRoleCode =
  "head_teacher" | "subject_teacher" | "academic_director";

export interface StaffRoleOption {
  code: StaffRoleCode;
  name: string;
  description: string;
}

export interface StaffAccount {
  id: number;
  name: string;
  phone: string;
  status: "active" | "disabled";
  roles: Array<StaffRoleCode | "school_admin">;
  is_school_admin: boolean;
  teacher_level?: string | null;
  frozen?: boolean;
  freeze_reason?: string | null;
}

export interface StaffDirectory {
  accounts: StaffAccount[];
  roles: StaffRoleOption[];
}

export type OrganizationUnitType =
  "department" | "grade_group" | "subject_group" | "admin_class";

export interface OrganizationUnit {
  id: number;
  parent_id: number | null;
  name: string;
  unit_type: OrganizationUnitType;
  subject_id?: number | null;
  grade_id?: number | null;
  academic_year: string | null;
  cohort_label: string | null;
  sort_order: number;
  status: "active" | "archived";
  member_count: number;
  children: OrganizationUnit[];
}

export interface OrganizationTreeResult {
  school: { id: number; name: string };
  units: OrganizationUnit[];
}

export interface StaffAppointment {
  id: number;
  organization_unit_id: number;
  organization_name: string;
  staff_id: number;
  staff_name: string;
  position_code:
    | "principal"
    | "academic_director"
    | "grade_director"
    | "head_teacher"
    | "deputy_head_teacher"
    | "member";
  academic_year: string | null;
  status: "active" | "archived";
}

export interface Campus {
  id: number;
  name: string;
  address: string | null;
  student_capacity: number | null;
  status: string;
}
export interface Building {
  id: number;
  campus_id: number;
  name: string;
  code: string | null;
  floor_count: number;
  status: string;
  room_count: number;
  multimedia_count: number;
}
export interface FacilityOverview {
  campuses: Campus[];
  buildings: Building[];
  stats: {
    campus_count: number;
    building_count: number;
    room_count: number;
    multimedia_count: number;
  };
}
export interface RoomResource {
  id: number;
  building_id: number;
  building_name: string;
  name: string;
  code: string | null;
  floor: number;
  capacity: number;
  room_type:
    | "classroom"
    | "laboratory"
    | "computer"
    | "meeting"
    | "auditorium"
    | "office";
  features: string[] | Record<string, unknown> | null;
  is_schedulable: boolean;
  is_exam_enabled: boolean;
  is_meeting_enabled: boolean;
  status: string;
  cohort_allocations?: Array<{
    rule_id: number;
    cohort_label: string;
    academic_year: string;
    term: string;
    allocation_mode: "exclusive" | "shared";
  }>;
  class_assignments?: Array<{
    id: number;
    name: string;
    grade_id: number;
    grade_name: string;
  }>;
}
export interface ResourceAllocationRule {
  id: number;
  name: string;
  cohort_label: string;
  academic_year: string;
  term: string;
  campus_id: number;
  building_id: number | null;
  building_ids: number[] | null;
  floor_from: number | null;
  floor_to: number | null;
  room_type: RoomResource["room_type"] | null;
  min_capacity: number | null;
  required_feature: string | null;
  allocation_mode: "exclusive" | "shared";
  status: string;
  matched_room_count: number;
}
export interface RoomAllocationPreview extends RoomResource {
  state: "available" | "occupied" | "current" | "ineligible" | "unavailable";
  selectable: boolean;
  occupied_by: string[];
  matches_rule: boolean;
}
export interface AllocationPreviewResult {
  matched_count: number;
  occupied_count: number;
  student_count: number | null;
  available_capacity: number;
  capacity_sufficient: boolean;
  capacity_gap: number | null;
  recommended_room_count: number | null;
  rooms: RoomAllocationPreview[];
}
export interface MeetingRecord {
  id: number;
  title: string;
  room_id: number;
  room_name: string;
  organizer_id: number;
  start_at: string;
  end_at: string;
  participant_ids: number[];
  agenda: string | null;
  status: string;
}

/** 年级 */
export interface Grade {
  id: number;
  campus_id?: number | null;
  campus_name?: string | null;
  name: string;
  level?: number;
  stage?: string;
  sort_order?: number;
}

/** 班级 */
export interface ClassInfo {
  id: number;
  grade_id: number;
  campus_id?: number | null;
  home_room_id?: number | null;
  resource_assigned?: boolean;
  planned_student_count?: number | null;
  class_type?: string;
  name: string;
  /** 届（毕业年，如 2029）；同一届班级随学年升级整体改挂年级 */
  cohort_label?: string | null;
  head_teacher_id?: number;
  head_teacher_name?: string;
  student_count?: number;
}

export interface AutoClassAssignmentClassResult {
  id: number;
  name: string;
  capacity: number;
  student_count: number;
  male_count: number;
  female_count: number;
  average_score: number | null;
  students: Array<{
    id: number;
    name: string;
    student_no?: string | null;
    gender: string;
    score?: number | null;
  }>;
}

export interface AutoClassAssignmentResult {
  grade_id: number;
  paper_id?: number | null;
  strategy: string;
  classes: AutoClassAssignmentClassResult[];
  assignments: Array<{ student_id: number; class_id: number }>;
  unassigned_count: number;
  total_students: number;
  assigned_student_count?: number;
  available_class_count?: number;
  required_class_count?: number;
  unused_class_count?: number;
}

/** 学生 */
export interface Student {
  id: number;
  campus_id?: number | null;
  grade_id?: number | null;
  grade_name?: string | null;
  class_id?: number | null;
  class_name?: string | null;
  student_no?: string;
  name: string;
  gender?: string;
  birth_date?: string;
  id_card?: string;
  parent_phone?: string;
  seat_no?: number;
  checkin_status?: string;
  status?: string;
}

/** 学生与年级部的学年快照关系 */
export interface StudentGradeMembership {
  id: number;
  student_id: number;
  student_no?: string | null;
  student_name?: string | null;
  grade_id: number;
  grade_name?: string | null;
  grade_unit_id: number;
  grade_unit_name?: string | null;
  academic_year: string;
  cohort_label?: string | null;
  status: string;
}

/** 排课基础资源 */
export interface TeacherInfo {
  id: number;
  name: string;
  phone?: string;
}

export interface SubjectInfo {
  id: number;
  tenant_id?: number | null;
  name: string;
  course_type?: "subject" | "activity";
  evening_study_allowed?: boolean;
}

export type WeekParity = "all" | "odd" | "even";
export type EveningParity = "all" | "odd" | "even" | "either";

export interface CourseHourPlanInfo {
  id: number;
  tenant_id: number;
  class_id: number;
  class_name?: string;
  subject_id: number;
  subject_name?: string;
  academic_year: string;
  term: string;
  weekday_periods: number;
  saturday_periods: number;
  weekly_periods: number;
  week_parity: WeekParity;
  evening_parity?: EveningParity;
  evening_periods_odd: number;
  evening_periods_even: number;
}

export interface TeachingAssignment {
  id: number;
  teacher_id: number | null;
  teacher_name?: string;
  subject_id: number;
  subject_name?: string;
  class_id: number;
  class_name?: string;
  academic_year: string;
  term: string;
  weekly_periods: number;
  room?: string | null;
}

export interface TeacherScopeRule {
  teacher_id: number;
  teacher_name?: string;
  class_id: number;
  class_name?: string;
  subject_id?: number | null;
  mode: "allow" | "deny";
  weekly_periods?: number | null;
  fixed_weekday?: number | null;
  fixed_period?: number | null;
}

export interface SchedulingResources {
  teachers: TeacherInfo[];
  subjects: SubjectInfo[];
  classes: ClassInfo[];
  assignments: TeachingAssignment[];
  teaching_track_subject_ids?: number[];
  teacher_subject_ids?: Record<string, number[]>;
}

export type SchedulingRuleTargetType =
  "global" | "slot" | "subject" | "teacher" | "class";
export type SchedulingRuleCode =
  | "slot_forbidden"
  | "slot_allowed"
  | "slot_fixed"
  | "teacher_daily_limit"
  | "teacher_consecutive"
  | "teacher_gap_free"
  | "class_gap_free"
  | "teacher_multi_class_evening_adjacent"
  | "teacher_forbidden_slots"
  | "teacher_preferred_weekdays"
  | "teacher_evening_daytime_link"
  | "teacher_period_minimum"
  | "subject_consecutive"
  | "subject_allowed_slots"
  | "class_allowed_subjects"
  | "class_slot_pattern"
  | "class_evening_self_study_day"
  | "slot_teacher_role_required"
  | "slot_teacher_balance"
  | "subject_evening_parity_pair"
  | "subject_daytime_parity_pair"
  | "manual_review"
  | "subject_prefer_early_periods"
  | "subject_gap_fill_late_periods";

export interface SchedulingRuleDefinition {
  id: string;
  title: string;
  code: SchedulingRuleCode;
  rule_scope?: "general" | "individual";
  enabled: boolean;
  priority: "hard" | "soft";
  target: { type: SchedulingRuleTargetType; ids: number[] };
  weekdays: number[];
  periods: number[];
  period_scope: "regular" | "evening" | "any";
  week_parity: "all" | "odd" | "even";
  params: Record<string, unknown>;
}

export interface SchedulingRuleGroup {
  id: string;
  name: string;
  academic_year: string;
  term: string;
  version: number;
  grade_id?: number | null;
  rules: SchedulingRuleDefinition[];
}

export interface SchedulingRuleGroupCatalog {
  catalog_version: number;
  active_id: string | null;
  groups: SchedulingRuleGroup[];
}

export interface SchedulingRuleEvaluationResult {
  rule_id: string;
  code: SchedulingRuleCode;
  title: string;
  priority: "hard" | "soft";
  status: "pass" | "fail" | "unresolved" | "not_run" | "manual";
  violation_count: number;
  penalty: number;
  metrics: Record<string, number | string>;
  message: string;
}

export interface SchedulingRuleValidationResult {
  valid: boolean;
  compiled: boolean;
  schedule_available: boolean;
  schedule_item_count: number;
  results: SchedulingRuleEvaluationResult[];
  unresolved: Array<{ rule_id: string; message: string }>;
  score: number;
}

export interface ScheduleEntry {
  id: number;
  class_id: number;
  class_name?: string;
  weekday: number;
  period: number;
  subject_id: number;
  subject_name?: string;
  teacher_id?: number | null;
  teacher_name?: string;
  room?: string | null;
  academic_year: string;
  term: string;
  week_parity?: "all" | "odd" | "even";
  lesson_date?: string;
}

export interface SchedulingGridConfig {
  configured?: boolean;
  days: number;
  periods_per_day: number;
  daily_periods: number[];
  enable_saturday: boolean;
  enable_evening: boolean;
  evening_start_period?: number | null;
  evening_daily_periods_odd: number[];
  evening_daily_periods_even: number[];
  evening_subject_ids: number[];
  evening_subject_ids_odd: number[];
  evening_subject_ids_even: number[];
  evening_subject_ids_odd_by_day?: Array<number | null>;
  evening_subject_ids_even_by_day?: Array<number | null>;
  term_start_monday?: string | null;
  first_week_parity: "odd" | "even";
}

/** 排课前资源校验：单条无解条件（后端 /scheduling/validate） */
export interface ScheduleValidationIssue {
  code:
    | "class_capacity_exceeded"
    | "teacher_capacity_exceeded"
    | "subject_capacity_exceeded"
    | "primary_admin_track_conflict";
  message: string;
  entity_type: "class" | "teacher" | "class_subject";
  entity_id: number;
  related_id?: number | null;
  requested: number;
  capacity: number;
  severity?: "error" | "warning";
  rule_code?: string | null;
  formula?: string | null;
  suggestions?: ScheduleRuleSuggestion[];
}

export interface ScheduleRuleSuggestion {
  code: string;
  label: string;
  field:
    | "days"
    | "periods_per_day"
    | "max_class_lessons_per_day"
    | "max_teacher_lessons_per_day"
    | "max_same_subject_per_day"
    | "weekly_periods"
    | "class_total_weekly_periods"
    | "teacher_total_weekly_periods";
  recommended_value: number;
  reason: string;
  tradeoff: string;
}

export interface ScheduleRuleExplanation {
  code: string;
  label: string;
  formula: string;
  result: number;
  description: string;
}

export interface ScheduleRuleConfig {
  days: number;
  periods_per_day: number;
  /** 周六专用课位；0 表示不开周六，兼容旧模板 */
  saturday_periods?: number;
  /** 旧模板兼容字段；周六现在固定为每周，隔周由任教关系的 0.5 课时表达 */
  saturday_parity?: "all" | "odd" | "even";
  /** 是否启用单双周晚自习配置 */
  enable_evening?: boolean;
  /** 晚自习起始节次；由正式课每天上限 + 1 推导，前端保存前会校正 */
  evening_start_period?: number | null;
  /** 周一至周日每天的单周晚自习节数 */
  evening_daily_periods_odd?: number[];
  /** 周一至周日每天的双周晚自习节数 */
  evening_daily_periods_even?: number[];
  /** 允许进入晚自习的学科，由规则模板保存 */
  evening_subject_ids?: number[];
  /** 单周允许进入晚自习的主课科目 */
  evening_subject_ids_odd?: number[];
  /** 双周允许进入晚自习的主课科目 */
  evening_subject_ids_even?: number[];
  /** 单周周一至周日的晚自习科目；null 表示自主学习 */
  evening_subject_ids_odd_by_day?: Array<number | null>;
  /** 双周周一至周日的晚自习科目；null 表示自主学习 */
  evening_subject_ids_even_by_day?: Array<number | null>;
  max_class_lessons_per_day: number;
  max_teacher_lessons_per_day: number;
  /** 周六独立负载上限，不与工作日上限联动 */
  max_class_lessons_on_saturday?: number;
  max_teacher_lessons_on_saturday?: number;
  /** 体育教师每日授课上限 */
  max_pe_teacher_lessons_per_day?: number;
  /** 教师每周最多课时（可省略，默认 30；旧规则模板无此字段） */
  max_teacher_weekly_periods?: number;
  /** 体育课每周节数（可省略；未设置时按默认每周课时处理） */
  pe_weekly_periods?: number;
  max_same_subject_per_day: number;
  require_full_week: boolean;
  avoid_consecutive_teacher_lessons: boolean;
  forbidden_slots: string[];
  strategy_codes: string[];
}

export interface ScheduleRuleTemplate {
  id: string;
  name: string;
  desc?: string;
  config: ScheduleRuleConfig;
  /** 模板级教师任教范围：allow/deny + 周课时/固定时段。切换默认模板时会自动同步到全局。 */
  scope_rules?: TeacherScopeRule[];
  /** 是否启用：停用的模板不可设为默认、不参与生成（默认 true，兼容旧数据） */
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ScheduleStrategyOption {
  code: string;
  name: string;
  description: string;
}

/** 排课前资源校验结果 */
export interface ScheduleValidationResult {
  valid: boolean;
  issues: ScheduleValidationIssue[];
  assignment_count: number;
  requested_lessons: number;
  available_slots: number;
  rules?: ScheduleRuleExplanation[];
  suggestions?: ScheduleRuleSuggestion[];
}

/** 课表历史版本摘要 */
export interface ScheduleVersionSummary {
  version_id: number;
  saved_at: string;
  academic_year: string;
  term: string;
  class_count: number;
  lesson_count: number;
  /** 形如 "第 1 版 · 2026-08-25 15:30:12" */
  label: string;
}

export interface SeatEntry {
  row: number;
  col: number;
  student_id: number;
  student_name?: string;
  student_no?: string | null;
  gender?: string | null;
  height_cm?: number | null;
}

export interface SeatArrangement {
  id: number;
  class_id: number;
  rows: number;
  cols: number;
  rule: string;
  layout: string;
  status: string;
  seats: SeatEntry[];
  effective_from?: string | null;
  effective_to?: string | null;
  created_at?: string;
}

export interface ExamScheduleEntry {
  id: number;
  exam_id: number;
  paper_id: number;
  paper_title?: string;
  grade_id: number;
  grade_name?: string;
  subject_id: number;
  subject_name?: string;
  exam_date: string;
  session_index: number;
  start_time: string;
  end_time: string;
  room: string;
  invigilator_id?: number | null;
  invigilator_name?: string;
}

export interface ExamRoomEntry {
  id: number;
  name: string;
  capacity: number;
  building?: string | null;
  room_type: "standard" | "special" | "reserve";
  status: "available" | "maintenance" | "disabled";
  source_class_id?: number | null;
}

export interface ExamSchedulingConfig {
  exam_id: number;
  grade_ids: number[];
  start_date?: string | null;
  excluded_dates: string[];
  sessions: Array<{ start_time: string; end_time: string }>;
  invigilators_per_room: number;
}

export interface ExamInvigilatorEntry {
  teacher_id: number;
  teacher_name: string;
  account_status: "active" | "disabled";
  enabled: boolean;
  leave_start?: string | null;
  leave_end?: string | null;
  unavailable_slots: string[];
  note?: string | null;
  assigned_count: number;
  state:
    "available" | "assigned" | "leave" | "excluded" | "disabled" | "conflict";
}

export interface ExamVenuePlan {
  confirmed: boolean;
  rooms: Array<{
    id?: number;
    name: string;
    capacity: number;
    source_type: "classroom" | "custom";
    source_class_id?: number | null;
  }>;
  summary: { room_count: number; seat_count: number };
}

export interface ExamRoomAssignment {
  id: number;
  grade_id: number;
  subject_id: number;
  exam_date: string;
  session_index: number;
  start_time?: string;
  end_time?: string;
  room_name: string;
  capacity: number;
  candidate_count: number;
  subject_name: string;
  grade_name: string;
  invigilator_names: string[];
}

export interface ExamPlan {
  mode: string;
  schedules: ExamScheduleEntry[];
  rooms: ExamRoomAssignment[];
  summary: {
    day_count: number;
    session_count: number;
    room_count: number;
    student_count: number;
    candidate_assignment_count: number;
    invigilator_count: number;
  };
}

export interface ExamCandidateAssignment {
  id: number;
  grade_id: number;
  subject_id: number;
  exam_date: string;
  session_index: number;
  start_time: string;
  end_time: string;
  room_name: string;
  seat_no: number;
  student_name: string;
  student_no?: string | null;
  subject_name: string;
  grade_name: string;
}

/** 考试状态 */
export const EXAM_STATUS = {
  PREPARING: "preparing",
  ONGOING: "ongoing",
  ENDED: "ended",
  ARCHIVED: "archived",
} as const;
export type ExamStatus = (typeof EXAM_STATUS)[keyof typeof EXAM_STATUS];

export const EXAM_STATUS_LABEL: Record<string, string> = {
  preparing: "筹备中",
  ongoing: "进行中",
  ended: "已结束",
  archived: "已归档",
};

/** 考试类型 */
export const EXAM_TYPE = {
  MONTHLY: "monthly",
  MIDTERM: "midterm",
  FINAL: "final",
  UNIT: "unit",
  OTHER: "other",
} as const;
export const EXAM_TYPE_LABEL: Record<string, string> = {
  monthly: "月考",
  midterm: "期中",
  final: "期末",
  unit: "单元测",
  other: "其他",
};

/** 考试 */
export interface Exam {
  id: number;
  name: string;
  status: ExamStatus | string;
  exam_type?: string;
  academic_year?: string;
  created_by?: number;
  created_at?: string;
  paper_count?: number;
}

/** 试卷状态 */
export const PAPER_STATUS = {
  BUILDING: "building",
  FINALIZED: "finalized",
} as const;
export const PAPER_STATUS_LABEL: Record<string, string> = {
  building: "建卷中",
  finalized: "已定稿",
};

/** 试卷 */
export interface Paper {
  id: number;
  exam_id?: number;
  subject_id?: number;
  grade_id?: number;
  teacher_id?: number;
  title: string;
  total_score?: number;
  status?: string;
  created_at?: string;
  delivered_at?: string;
  questions?: Question[];
  actual_score?: number;
}

/** 题目难度 */
export const DIFFICULTY = {
  BASIC: "basic",
  MEDIUM: "medium",
  HARD: "hard",
} as const;
export const DIFFICULTY_LABEL: Record<string, string> = {
  basic: "基础",
  medium: "中档",
  hard: "拔高",
};

/** 题目 */
export interface Question {
  id: number;
  paper_id: number;
  question_no: number;
  score: number;
  knowledge_point_id?: number | null;
  difficulty?: string;
  content?: string | null;
  question_type?: string | null;
  source_type?: string | null;
  created_at?: string;
}

/** 扫描批次状态 */
export const SCAN_BATCH_STATUS = {
  UPLOADED: "uploaded",
  SPLIT: "split",
  ASSIGNED: "assigned",
  CONFIRMED: "confirmed",
} as const;
export const SCAN_BATCH_STATUS_LABEL: Record<string, string> = {
  uploaded: "已上传",
  split: "已切分",
  assigned: "已分配",
  confirmed: "已确认",
};

/** 扫描批次 */
export interface ScanBatch {
  id: number;
  paper_id: number;
  file_name?: string | null;
  page_count?: number;
  status?: string;
  created_by?: number;
  created_at?: string;
}

/** 作答（一生一卷，阅卷队列项） */
export interface Submission {
  id: number;
  paper_id: number;
  student_id: number;
  student_name?: string | null;
  total_score?: number;
  status?: string;
  scored_questions?: number;
}

/** 作答详情（含每题状态） */
export interface SubmissionDetail {
  submission: Submission;
  student_name?: string | null;
  questions: Array<{
    question_id: number;
    question_no: number;
    score: number;
    difficulty?: string | null;
    content?: string | null;
    given_score: number | null;
    ai_score: number | null;
    ai_confidence: number | null;
    confirm_status: string | null;
  }>;
}

/** 每题得分（服务端 upsert 返回） */
export interface AnswerScore {
  id?: number;
  submission_id: number;
  question_id: number;
  score: number;
  ai_score?: number | null;
  ai_confidence?: number | null;
  grading_mode?: string;
  confirm_status?: string;
}

/** 成绩汇总（按卷） */
export interface PaperSummary {
  paper_id: number;
  count: number;
  mean: number;
  max: number;
  min: number;
  distribution?: Array<{ label: string; count: number }>;
}

/** 菜单节点（后端 /auth/menus 返回，available=false 渲染为"待开放"） */
export interface MenuNode {
  key: string;
  title: string;
  icon: string;
  path?: string | null;
  available: boolean;
  children?: MenuNode[];
}

/** 菜单响应体 */
export interface MenuResult {
  menus: MenuNode[];
  gaokao_mode?: "3+1+2" | "3+3" | "traditional";
}

/** 教师职务标签（截图样式："2029届高一年级部·组织成员 ×"） */
export interface TeacherPositionTag {
  organization_unit_id: number;
  organization_name: string;
  position_code: string;
  display_text: string;
}

/** 任教班级条目 */
export interface TeacherTeachingClass {
  class_id: number;
  class_name: string;
  subject_id: number;
  subject_name: string;
  weekly_periods: number;
}

/** 教师档案行 */
export interface TeacherProfile {
  teacher_id: number;
  name: string;
  phone: string;
  is_head_teacher: boolean;
  head_teacher_classes: string[];
  position_tags: TeacherPositionTag[];
  teaching_classes: TeacherTeachingClass[];
  total_weekly_periods: number;
  scheduled_lessons_count: number;
  schedule_ratio: number;
}

/** 教师筛选条件默认值/基础项 */
export interface TeacherProfileFiltersMeta {
  defaults: {
    entry_year?: number | null;
    academic_year?: string | null;
    term: string;
  };
  cohort_orgs?: Record<
    string,
    Array<{ org_id: number; name: string; cohort_label: string | null }>
  >;
  grades: Array<{ grade_id: number; name: string; level: number }>;
  subjects?: Array<{ subject_id: number; name: string }>;
}

/** 教师档案：班级视角汇总（顶部统计卡口径） */
export interface TeacherProfileClassSummary {
  /** 筛选条件覆盖的行政班总数 */
  class_count: number;
  /** 周目标：课时管理方案折合周课时之和（含周六、晚自习；无方案时回退课位×班级数） */
  weekly_target: number;
  /** 已排折合周课时（单/双周各 0.5） */
  scheduled_lessons: number;
  /** 完成度百分比：scheduled_lessons / weekly_target × 100，保留1位小数 */
  completion_ratio: number;
}

/** 教师档案列表结果 */
export interface TeacherProfileListResult {
  defaults: TeacherProfileFiltersMeta["defaults"];
  items: TeacherProfile[];
  total: number;
  /** 班级视角汇总（新增口径：班级数 × 30 / 已排节数） */
  class_summary?: TeacherProfileClassSummary;
}

/** 教师个人课表项（同 ScheduleEntry） */
export interface TeacherScheduleEntry {
  id: number;
  class_id: number;
  weekday: number;
  period: number;
  subject_id: number;
  teacher_id: number;
  room: string | null;
  academic_year: string;
  term: string;
  week_parity?: "all" | "odd" | "even";
  teacher_name?: string;
  subject_name?: string;
  class_name?: string;
}

/** 教师个人周课表结果 */
export interface TeacherWeeklyScheduleResult {
  teacher_name?: string;
  items: TeacherScheduleEntry[];
}

/** 平台超管 */
export interface PlatformAdminInfo {
  id: number;
  username: string;
  name: string;
}

/** 平台端·学校(租户) */
export interface AdminSchool {
  id: number;
  code: string;
  name: string;
  type: string;
  province: string;
  gaokao_mode: "3+1+2" | "3+3" | "traditional";
  created_at: string;
  admin_phone?: string | null;
  admin_status?: string | null;
  frozen?: boolean | null;
  freeze_reason?: string | null;
  last_login_at?: string | null;
}

export type GaokaoMode = "3+1+2" | "3+3" | "traditional";

/** 应用配置常量 */
export const APP_NAME = "轻课堂";
export const APP_NAME_EN = "LightClass";

/** 默认学校代码：私有化部署/演示，与后端 config.default_school_code 保持同值 */
export const DEFAULT_SCHOOL_CODE = "demo";

/** ---------- 角色与权限（RBAC） ---------- */

/** 角色 */
export interface RoleInfo {
  id: number;
  code: string;
  name: string;
  description: string;
  builtin: boolean;
  permission_count: number;
  member_count: number;
}

export interface RoleMember {
  id: number;
  name: string;
  phone: string;
  status: "active" | "disabled";
  assigned: boolean;
  assignable: boolean;
}

export interface RoleMembersResult {
  role: Pick<RoleInfo, "id" | "code" | "name">;
  editable: boolean;
  members: RoleMember[];
}

/** 权限点 */
export interface PermissionItem {
  code: string;
  name: string;
}

/** 权限点目录（按模块分组） */
export interface PermissionGroup {
  module: string;
  permissions: PermissionItem[];
}

/** 角色菜单预览（按权限码模拟侧栏） */
export interface RoleMenuPreview {
  menus: MenuNode[];
  matched_permissions: Record<string, string[]>;
  permission_codes: string[];
}

/** 菜单可见权限映射（管理台） */
export interface MenuPermissionBinding {
  key: string;
  title: string;
  path: string | null;
  icon: string;
  group: string;
  role_fallback: string[];
  permission_codes: string[];
  configured: boolean;
}
