/**
 * 智衡 ZhiHeng · 共享类型 / 枚举 / 常量（前端各包复用）
 */

/** 后端统一响应结构：成功 code=0 */
export interface ApiResponse<T = unknown> {
  code: number
  message: string
  data: T
}

/** 用户 */
export interface UserInfo {
  id: number
  name: string
  phone?: string
  role?: string
  roles?: string[]
  school_code?: string
}

export type StaffRoleCode = 'head_teacher' | 'subject_teacher' | 'academic_director'

export interface StaffRoleOption {
  code: StaffRoleCode
  name: string
  description: string
}

export interface StaffAccount {
  id: number
  name: string
  phone: string
  status: 'active' | 'disabled'
  roles: Array<StaffRoleCode | 'school_admin'>
  is_school_admin: boolean
}

export interface StaffDirectory {
  accounts: StaffAccount[]
  roles: StaffRoleOption[]
}

/** 年级 */
export interface Grade {
  id: number
  name: string
  level?: number
  stage?: string
  sort_order?: number
}

/** 班级 */
export interface ClassInfo {
  id: number
  grade_id: number
  name: string
  head_teacher_id?: number
  head_teacher_name?: string
  head_teacher_subject_name?: string
  head_teacher_taught_class_count?: number
  head_teacher_teaches_own_class?: boolean
  student_count?: number
}

/** 学生 */
export interface Student {
  id: number
  class_id?: number | null
  class_name?: string | null
  student_no?: string
  name: string
  gender?: string
  birth_date?: string
  id_card?: string
  parent_phone?: string
  height_cm?: number | null
  seat_no?: number
  checkin_status?: string
}

/** 排课基础资源 */
export interface TeacherInfo {
  id: number
  name: string
  phone?: string
}

export interface SubjectInfo {
  id: number
  name: string
  course_type?: 'subject' | 'activity'
}

export interface TeachingAssignment {
  id: number
  teacher_id: number | null
  teacher_name?: string
  subject_id: number
  subject_name?: string
  class_id: number
  class_name?: string
  academic_year: string
  term: string
  weekly_periods: number
  room?: string | null
}

export interface SchedulingResources {
  teachers: TeacherInfo[]
  subjects: SubjectInfo[]
  classes: ClassInfo[]
  assignments: TeachingAssignment[]
}

export interface ScheduleValidationIssue {
  code: 'class_capacity_exceeded' | 'teacher_capacity_exceeded' | 'subject_capacity_exceeded'
  message: string
  entity_type: 'class' | 'teacher' | 'class_subject'
  entity_id: number
  related_id?: number | null
  requested: number
  capacity: number
}

export interface ScheduleValidationResult {
  valid: boolean
  issues: ScheduleValidationIssue[]
  assignment_count: number
  requested_lessons: number
  available_slots: number
}

export interface ScheduleStrategyOption {
  code: string
  name: string
  description: string
}

export interface ScheduleGenerationResult {
  created: number
  class_count: number
  unplaced: Array<{ assignment_id: number; count: number }>
  strategy_codes: string[]
  staffing_issues: ScheduleStaffingIssue[]
  validation: Omit<ScheduleValidationResult, 'valid' | 'issues'>
}

export interface ScheduleStaffingIssue {
  class_id: number
  class_name?: string
  subject_id: number
  subject_name?: string
  teacher_id: number
  teacher_name?: string
  weekday: number
  gap_period: number
  scheduled_period: number
  blocking_class_id: number
  blocking_class_name?: string
  additional_teachers: number
}

export interface ScheduleEntry {
  id: number
  class_id: number
  class_name?: string
  weekday: number
  period: number
  subject_id: number
  subject_name?: string
  teacher_id?: number | null
  teacher_name?: string
  room?: string | null
  academic_year: string
  term: string
  lesson_date?: string
}

export interface SeatEntry {
  row: number
  col: number
  student_id: number
  student_name?: string
  student_no?: string | null
  gender?: string | null
}

export interface SeatArrangement {
  id: number
  class_id: number
  rows: number
  cols: number
  rule: string
  status: string
  seats: SeatEntry[]
  effective_from?: string | null
  effective_to?: string | null
  created_at?: string
}

export interface ExamScheduleEntry {
  id: number
  exam_id: number
  paper_id: number
  paper_title?: string
  grade_id: number
  grade_name?: string
  subject_id: number
  subject_name?: string
  exam_date: string
  session_index: number
  start_time: string
  end_time: string
  room: string
  invigilator_id?: number | null
  invigilator_name?: string
}

export interface ExamRoomAssignmentEntry {
  id: number
  exam_id: number
  exam_schedule_id: number
  paper_id: number
  grade_id: number
  grade_name?: string
  subject_id: number
  subject_name?: string
  exam_date: string
  session_index: number
  room_name: string
  capacity: number
  candidate_count: number
  invigilator_ids: number[]
  invigilator_names: string[]
}

export interface ExamVenueEntry {
  id?: number
  exam_id?: number
  name: string
  capacity: number
  source_type: 'classroom' | 'custom'
  source_class_id?: number | null
  confirmed_at?: string
}

export interface ExamVenuePlan {
  confirmed: boolean
  rooms: ExamVenueEntry[]
  summary: { room_count: number; seat_count: number }
}

export interface ExamRoomCatalogEntry {
  id: number
  name: string
  capacity: number
  building?: string | null
  room_type: 'standard' | 'special' | 'reserve'
  source_class_id?: number | null
  is_deleted: boolean
}

export interface ExamPlan {
  mode: string
  schedules: ExamScheduleEntry[]
  rooms: ExamRoomAssignmentEntry[]
  summary: {
    day_count: number
    session_count: number
    room_count: number
    student_count: number
    candidate_assignment_count: number
    invigilator_count: number
  }
}

export interface ExamCandidateAssignmentEntry {
  id: number
  student_id: number
  student_name: string
  student_no?: string | null
  grade_name?: string
  subject_name?: string
  exam_date: string
  session_index: number
  start_time: string
  end_time: string
  room_name: string
  seat_no: number
}

/** 考试状态 */
export const EXAM_STATUS = {
  PREPARING: 'preparing', // 筹备
  ONGOING: 'ongoing',     // 进行
  ENDED: 'ended',         // 已结束
  ARCHIVED: 'archived',   // 已归档
} as const
export type ExamStatus = (typeof EXAM_STATUS)[keyof typeof EXAM_STATUS]

export const EXAM_STATUS_LABEL: Record<string, string> = {
  preparing: '筹备中',
  ongoing: '进行中',
  ended: '已结束',
  archived: '已归档',
}

/** 考试类型 */
export const EXAM_TYPE = {
  MONTHLY: 'monthly',   // 月考
  MIDTERM: 'midterm',   // 期中
  FINAL: 'final',       // 期末
  UNIT: 'unit',         // 单元测
  OTHER: 'other',
} as const
export const EXAM_TYPE_LABEL: Record<string, string> = {
  monthly: '月考',
  midterm: '期中',
  final: '期末',
  unit: '单元测',
  other: '其他',
}

/** 考试 */
export interface Exam {
  id: number
  name: string
  status: ExamStatus | string
  exam_type?: string
  academic_year?: string
  created_by?: number
  created_at?: string
  paper_count?: number
}

/** 试卷状态 */
export const PAPER_STATUS = {
  BUILDING: 'building',   // 建卷中
  FINALIZED: 'finalized', // 已定稿
} as const
export const PAPER_STATUS_LABEL: Record<string, string> = {
  building: '建卷中',
  finalized: '已定稿',
}

/** 试卷 */
export interface Paper {
  id: number
  exam_id?: number
  subject_id?: number
  grade_id?: number
  teacher_id?: number
  title: string
  total_score?: number
  status?: string
  created_at?: string
  delivered_at?: string
  // 详情附加
  questions?: Question[]
  actual_score?: number
}

/** 题目难度 */
export const DIFFICULTY = {
  BASIC: 'basic',   // 基础
  MEDIUM: 'medium', // 中档
  HARD: 'hard',     // 拔高
} as const

export const DIFFICULTY_LABEL: Record<string, string> = {
  basic: '基础',
  medium: '中档',
  hard: '拔高',
}

/** 题目 */
export interface Question {
  id: number
  paper_id: number
  question_no: number
  score: number
  knowledge_point_id?: number | null
  difficulty?: string
  content?: string | null
  question_type?: string | null
  source_type?: string | null
  created_at?: string
}

/** 扫描批次状态 */
export const SCAN_BATCH_STATUS = {
  UPLOADED: 'uploaded',   // 已上传
  SPLIT: 'split',         // 已切分
  ASSIGNED: 'assigned',   // 已分配
  CONFIRMED: 'confirmed', // 已确认
} as const

/** 扫描批次 */
export interface ScanBatch {
  id: number
  paper_id: number
  file_name?: string | null
  page_count?: number
  status?: string
  created_by?: number
  created_at?: string
}

/** 作答（一生一卷，阅卷队列项） */
export interface Submission {
  id: number
  paper_id: number
  student_id: number
  student_name?: string | null
  total_score?: number
  status?: string
  scored_questions?: number
}

/** 作答详情（含每题状态） */
export interface SubmissionDetail {
  submission: Submission
  student_name?: string | null
  questions: Array<{
    question_id: number
    question_no: number
    score: number
    difficulty?: string | null
    content?: string | null
    given_score: number | null
    ai_score: number | null
    ai_confidence: number | null
    confirm_status: string | null
  }>
}

/** 每题得分（服务端 upsert 返回） */
export interface AnswerScore {
  id?: number
  submission_id: number
  question_id: number
  score: number
  ai_score?: number | null
  ai_confidence?: number | null
  grading_mode?: string
  confirm_status?: string
}

/** 成绩汇总（按卷） */
export interface PaperSummary {
  paper_id: number
  count: number
  mean: number
  max: number
  min: number
  distribution?: Array<{ label: string; count: number }>
}

/** 菜单节点（后端 /auth/menus 返回，available=false 渲染为"待开放"） */
export interface MenuNode {
  key: string
  title: string
  icon: string
  path?: string | null
  available: boolean
  children?: MenuNode[]
}

/** 菜单响应体 */
export interface MenuResult {
  menus: MenuNode[]
  gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
}

/** 平台超管 */
export interface PlatformAdminInfo {
  id: number
  username: string
  name: string
}

/** 平台端·学校(租户) */
export interface AdminSchool {
  id: number
  code: string
  name: string
  type: string
  province: string
  gaokao_mode: '3+1+2' | '3+3' | 'traditional'
  created_at: string
  admin_phone?: string | null
}

/** Web 配置常量 */
export const APP_NAME = '智衡'
export const APP_NAME_EN = 'ZhiHeng'

/** 默认学校代码：私有化部署/演示，与后端 config.default_school_code 保持同值；有真实租户时经 X-School-Code 头覆盖 */
export const DEFAULT_SCHOOL_CODE = 'demo'

/** Element Plus 深浅场景配色 token（与视觉方案联动） */
export const THEME_TOKENS = {
  graphite950: '#202124',
  ink950: '#172033',
  ink700: '#344054',
  ink500: '#667085',
  blue600: '#1677E8',
  blue100: '#E8F1FF',
  navy700: '#2F4664',
  cyan500: '#15B8C9',
  green500: '#16A36A',
  amber500: '#F59E0B',
  orange500: '#FF684D',
  red500: '#E5484D',
  surface0: '#F6F8FC',
  surface1: '#FFFFFF',
  line: '#E5EAF2',
} as const
