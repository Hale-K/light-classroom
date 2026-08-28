// 业务枚举 / 状态 -> 中文标签（集中映射，页面用 <DictTag dict={X} value={v} /> 渲染）

export interface DictItem {
  label: string
  /** 预设色名（success/processing/default…）；与 bg 同时存在时表示文字色 */
  color?: string
  /** 自定义底色（hex）；存在时走内联样式 Tag */
  bg?: string
  /** 自定义边框色（配合 bg 使用） */
  border?: string
}
export type Dict = Record<string, DictItem>

/** 字典值 → 中文 label（未命中 → fallback，默认 '—'） */
export function dictLabel(dict: Dict, value?: string | number | null, fallback = '—'): string {
  return value != null && dict[String(value)] ? dict[String(value)].label : fallback
}

// ==================== 轻课堂 · 考试域 ====================

// exam.status
export const EXAM_STATUS_DICT: Dict = {
  preparing: { label: '筹备中', color: 'default' },
  ongoing: { label: '进行中', color: 'processing' },
  ended: { label: '已结束', color: 'success' },
  archived: { label: '已归档', color: 'default' },
}

// exam.exam_type
export const EXAM_TYPE_DICT: Dict = {
  monthly: { label: '月考', color: 'blue' },
  midterm: { label: '期中', color: 'geekblue' },
  final: { label: '期末', color: 'purple' },
  unit: { label: '单元测', color: 'cyan' },
  other: { label: '其他', color: 'default' },
}

// paper.status
export const PAPER_STATUS_DICT: Dict = {
  building: { label: '建卷中', color: 'default' },
  finalized: { label: '已定稿', color: 'success' },
}

// question.difficulty
export const DIFFICULTY_DICT: Dict = {
  basic: { label: '基础', color: 'green' },
  medium: { label: '中档', color: 'orange' },
  hard: { label: '拔高', color: 'red' },
}

// ==================== 轻课堂 · 扫描 / 阅卷域 ====================

// scan_batch.status
export const SCAN_BATCH_STATUS_DICT: Dict = {
  uploaded: { label: '已上传', color: 'default' },
  split: { label: '已切分', color: 'processing' },
  assigned: { label: '已分配', color: 'geekblue' },
  confirmed: { label: '已确认', color: 'success' },
}

// submission.status
export const SUBMISSION_STATUS_DICT: Dict = {
  pending: { label: '待批阅', color: 'default' },
  grading: { label: '批阅中', color: 'processing' },
  finalized: { label: '已批完', color: 'success' },
}

// 评分确认状态
export const CONFIRM_STATUS_DICT: Dict = {
  pending: { label: '待确认', color: 'default' },
  ai: { label: 'AI 预判', color: 'cyan' },
  manual: { label: '人工确认', color: 'success' },
  confirmed: { label: '已确认', color: 'success' },
}

// ==================== 轻课堂 · 组织 / 人员域 ====================

// student.gender
export const GENDER_DICT: Dict = {
  male: { label: '男', color: 'blue' },
  female: { label: '女', color: 'magenta' },
  男: { label: '男', color: 'blue' },
  女: { label: '女', color: 'magenta' },
}

// student.status
export const STUDENT_STATUS_DICT: Dict = {
  studying: { label: '在读', color: 'success' },
  leave: { label: '休学', color: 'warning' },
  transferred: { label: '转出', color: 'default' },
}

// staff.status
export const STAFF_STATUS_DICT: Dict = {
  active: { label: '在职', color: 'success' },
  disabled: { label: '停用', color: 'default' },
}

// staff.roles
export const STAFF_ROLE_DICT: Dict = {
  school_admin: { label: '校长', color: 'gold' },
  academic_director: { label: '教导主任', color: 'geekblue' },
  head_teacher: { label: '班主任', color: 'cyan' },
  subject_teacher: { label: '任课老师', color: 'blue' },
}

// 用户角色（auth.me.role）
export const USER_ROLE_DICT: Dict = {
  director: { label: '校长', color: 'gold' },
  teacher: { label: '老师', color: 'blue' },
}

// ==================== 轻课堂 · 高考 / 排考域 ====================

// school.gaokao_mode
export const GAOKAO_MODE_DICT: Dict = {
  '3+1+2': { label: '3+1+2', color: 'blue' },
  '3+3': { label: '3+3', color: 'geekblue' },
  traditional: { label: '传统文理', color: 'default' },
}

// 排考场次
export const SESSION_INDEX_DICT: Dict = {
  0: { label: '上午', color: 'default' },
  1: { label: '下午', color: 'processing' },
}

// 座位安排状态
export const SEAT_STATUS_DICT: Dict = {
  draft: { label: '草稿', color: 'default' },
  active: { label: '生效中', color: 'success' },
  archived: { label: '已归档', color: 'default' },
}
