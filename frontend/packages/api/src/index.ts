/**
 * 各业务模块 API（对接 FastAPI 后端 /api/v1 真实端点）。
 * 返回类型从 @zhiheng/shared 复用；数据由 http 拦截器解包为业务 data。
 */
import { http, unwrap, setAuthResolver } from './http'
import type {
  AdminSchool,
  AnswerScore,
  ClassInfo,
  Exam,
  ExamCandidateAssignmentEntry,
  ExamPlan,
  ExamRoomCatalogEntry,
  ExamScheduleEntry,
  ExamVenueEntry,
  ExamVenuePlan,
  Grade,
  MenuResult,
  Paper,
  PaperSummary,
  PlatformAdminInfo,
  Question,
  ScanBatch,
  ScheduleEntry,
  ScheduleGenerationResult,
  ScheduleStrategyOption,
  ScheduleValidationResult,
  SchedulingResources,
  StaffAccount,
  StaffDirectory,
  StaffRoleCode,
  SeatArrangement,
  Student,
  Submission,
  SubmissionDetail,
  UserInfo,
} from '@zhiheng/shared'

/** 登录响应：后端 `{access_token, token_type, user, school}` */
export interface LoginResult {
  access_token: string
  token_type: string
  user: UserInfo
  /** 账号所属学校，登录后由后端决定，前端无需预选 */
  school?: {
    code: string | null
    name: string | null
    province: string | null
    gaokao_mode: '3+1+2' | '3+3' | 'traditional' | null
  }
}

export interface SchoolSettings {
  id: number
  code: string
  name: string
  province: string
  gaokao_mode: '3+1+2' | '3+3' | 'traditional'
}

export const authApi = {
  login: (phone: string, password: string) =>
    unwrap<LoginResult>(http.post('/auth/login', { phone, password })),
  register: (data: { name: string; phone: string; password: string; role?: string }) =>
    unwrap<UserInfo>(http.post('/auth/register', data)),
  me: () => unwrap<UserInfo>(http.get('/auth/me')),
  menus: () => unwrap<MenuResult>(http.get('/auth/menus')),
  school: () => unwrap<SchoolSettings>(http.get('/auth/school')),
  updateSchool: (data: { province?: string; gaokao_mode?: '3+1+2' | '3+3' | 'traditional' }) =>
    unwrap<SchoolSettings>(http.patch('/auth/school', data)),
}

/** 平台超管 API（创建学校后台） */
export const adminApi = {
  login: (username: string, password: string) =>
    unwrap<{ access_token: string; admin: PlatformAdminInfo }>(
      http.post('/admin/login', { username, password }),
    ),
  me: () => unwrap<PlatformAdminInfo>(http.get('/admin/me')),
  listSchools: () => unwrap<AdminSchool[]>(http.get('/admin/schools')),
  createSchool: (data: {
    code: string
    name: string
    province: string
    gaokao_mode: '3+1+2' | '3+3' | 'traditional'
    admin_name: string
    admin_phone: string
    admin_password: string
  }) => unwrap<AdminSchool>(http.post('/admin/schools', data)),
  updateSchool: (id: number, data: {
    name: string
    province?: string
    gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
    admin_phone?: string
  }) =>
    unwrap<AdminSchool>(http.put(`/admin/schools/${id}`, data)),
  resetPassword: (id: number, password: string) =>
    unwrap<{ school_id: number; phone: string | null }>(
      http.post(`/admin/schools/${id}/reset-password`, { password }),
    ),
  schoolStats: () => unwrap<{ total: number }>(http.get('/admin/schools/stats')),
}

export const orgApi = {
  grades: () => unwrap<Grade[]>(http.get('/org/grades')),
  createGrade: (data: { name: string; level: number }) =>
    unwrap<Grade>(http.post('/org/grades', data)),
  classes: (params?: { grade_id?: number; academic_year?: string; term?: string }) =>
    unwrap<ClassInfo[]>(http.get('/org/classes', { params })),
  createClass: (data: { grade_id: number; name: string; head_teacher_id?: number }) =>
    unwrap<ClassInfo>(http.post('/org/classes', data)),
  assignHeadTeacher: (classId: number, data: { teacher_id: number; academic_year: string; term: string }) =>
    unwrap<ClassInfo>(http.patch(`/org/classes/${classId}/head-teacher`, data)),
  students: (class_id?: number) =>
    unwrap<Student[]>(http.get('/org/students', { params: { class_id } })),
  createStudent: (data: Record<string, unknown>) =>
    unwrap<Student>(http.post('/org/students', data)),
  assignStudents: (student_ids: number[], class_id: number | null) =>
    unwrap<{ updated: number; class_id: number | null }>(
      http.patch('/org/students/assign-class', { student_ids, class_id }),
    ),
  studentCount: () => unwrap<{ total: number }>(http.get('/org/students/count')),
}

export const staffApi = {
  list: () => unwrap<StaffDirectory>(http.get('/staff')),
  create: (data: { name: string; phone: string; password: string; roles: StaffRoleCode[] }) =>
    unwrap<StaffAccount>(http.post('/staff', data)),
  updateRoles: (id: number, roles: StaffRoleCode[]) =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/roles`, { roles })),
  updateStatus: (id: number, status: 'active' | 'disabled') =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/status`, { status })),
}

export const schedulingApi = {
  resources: () => unwrap<SchedulingResources>(http.get('/scheduling/resources')),
  strategies: () => unwrap<ScheduleStrategyOption[]>(http.get('/scheduling/strategies')),
  createTeacher: (data: { name: string; phone: string; password: string }) =>
    unwrap(http.post('/scheduling/teachers', data)),
  createSubject: (name: string) => unwrap(http.post('/scheduling/subjects', { name })),
  saveAssignment: (data: {
    teacher_id: number
    subject_id: number
    class_id: number
    academic_year: string
    term: string
    weekly_periods: number
    room?: string
  }) => unwrap(http.post('/scheduling/assignments', data)),
  validate: (data: {
    academic_year: string
    term: string
    class_ids?: number[]
    days?: number
    periods_per_day?: number
    forbidden_slots?: Array<[number, number]>
    max_class_lessons_per_day?: number
    max_teacher_lessons_per_day?: number
    max_same_subject_per_day?: number
    strategy_codes?: string[]
    random_seed?: number
  }) => unwrap<ScheduleValidationResult>(http.post('/scheduling/validate', data)),
  generate: (data: {
    academic_year: string
    term: string
    class_ids?: number[]
    days?: number
    periods_per_day?: number
    forbidden_slots?: Array<[number, number]>
    max_class_lessons_per_day?: number
    max_teacher_lessons_per_day?: number
    max_same_subject_per_day?: number
    strategy_codes?: string[]
    random_seed?: number
  }) => unwrap<ScheduleGenerationResult>(
    http.post('/scheduling/generate', data),
  ),
  weekly: (params: { class_id: number; academic_year: string; term: string }) =>
    unwrap<ScheduleEntry[]>(http.get('/scheduling/weekly', { params })),
  calendar: (params: { class_id: number; academic_year: string; term: string; week_start: string }) =>
    unwrap<ScheduleEntry[]>(http.get('/scheduling/calendar', { params })),
}

export interface GaokaoOverview {
  scheme: { id: number; name: string; mode: '3+1+2' | '3+3' | 'traditional'; entry_year: number } | null
  grades: Grade[]
  stats: {
    student_count: number
    confirmed_count: number
    coverage_rate: number
    combination_count: number
    teaching_class_count: number
    schedule_period_count: number
  }
  combinations: Array<{ key: string; label: string; count: number; mode: string }>
  subject_demand: Array<{
    subject_id: number
    subject_name: string
    student_count: number
    recommended_class_count: number
    teaching_class_count: number
    teacher_count: number
  }>
}

export const gaokaoApi = {
  overview: (params: { academic_year: string; term: string; grade_id?: number }) =>
    unwrap<GaokaoOverview>(http.get('/gaokao/overview', { params })),
  generateTeachingClasses: (data: {
    grade_id: number; academic_year: string; term: string; capacity?: number; weekly_periods?: number
  }) => unwrap<{ created: number; memberships: number }>(http.post('/gaokao/teaching-classes/generate', data)),
  generateSchedule: (data: {
    grade_id: number; academic_year: string; term: string; days?: number; periods_per_day?: number
  }) => unwrap<{ created: number; unplaced: Array<{ teaching_class_id: number; count: number }> }>(
    http.post('/gaokao/schedules/generate', data),
  ),
}

export const seatingApi = {
  list: (class_id: number) =>
    unwrap<SeatArrangement[]>(http.get('/seating/arrangements', { params: { class_id } })),
  generate: (data: {
    class_id: number
    rows: number
    cols: number
    rule: string
    seed?: number
    front_student_ids?: number[]
    effective_from?: string
    effective_to?: string
  }) => unwrap<SeatArrangement>(http.post('/seating/generate', data)),
  activate: (id: number) =>
    unwrap<SeatArrangement>(http.patch(`/seating/arrangements/${id}/activate`)),
}

export const examSchedulingApi = {
  get: (examId: number) =>
    unwrap<ExamScheduleEntry[]>(http.get(`/exam-scheduling/${examId}`)),
  generate: (data: {
    exam_id: number
    start_date: string
    room: string
    sessions: Array<{ start_time: string; end_time: string }>
    excluded_dates?: string[]
    }) => unwrap<ExamScheduleEntry[]>(http.post('/exam-scheduling/generate', data)),
  getPlan: (examId: number) =>
    unwrap<ExamPlan>(http.get(`/exam-scheduling/plans/${examId}`)),
  venues: (examId: number) =>
    unwrap<ExamVenuePlan>(http.get(`/exam-scheduling/exams/${examId}/venues`)),
  saveVenues: (examId: number, rooms: ExamVenueEntry[]) =>
    unwrap<ExamVenuePlan>(http.put(`/exam-scheduling/exams/${examId}/venues`, { rooms })),
  rooms: (params: { keyword?: string; page?: number; page_size?: number } = {}) =>
    unwrap<{
      items: ExamRoomCatalogEntry[]
      pagination: { page: number; page_size: number; total: number; total_pages: number }
    }>(http.get('/exam-scheduling/rooms', { params })),
  createRoom: (data: { name: string; capacity: number; building?: string; room_type: string }) =>
    unwrap<ExamRoomCatalogEntry>(http.post('/exam-scheduling/rooms', data)),
  updateRoom: (id: number, data: { name?: string; capacity?: number; building?: string | null; room_type?: string }) =>
    unwrap<ExamRoomCatalogEntry>(http.patch(`/exam-scheduling/rooms/${id}`, data)),
  deleteRoom: (id: number) => unwrap<{ id: number }>(http.delete(`/exam-scheduling/rooms/${id}`)),
  generatePlan: (data: {
    exam_id: number
    grade_ids?: number[]
    start_date: string
    room: string
    sessions: Array<{ start_time: string; end_time: string }>
    excluded_dates?: string[]
    rooms?: Array<{ name: string; capacity: number }>
    invigilators_per_room?: number
  }) => unwrap<ExamPlan>(http.post('/exam-scheduling/plans', data)),
  candidates: (examId: number, params: {
    room_assignment_id?: number
    keyword?: string
    page?: number
    page_size?: number
  }) => unwrap<{
    items: ExamCandidateAssignmentEntry[]
    pagination: { page: number; page_size: number; total: number; total_pages: number }
  }>(http.get(`/exam-scheduling/plans/${examId}/candidates`, { params })),
}

export const examApi = {
  list: () => unwrap<Exam[]>(http.get('/exams')),
  create: (data: { name: string; exam_type: string; academic_year: string }) =>
    unwrap<Exam>(http.post('/exams', data)),
  detail: (id: number) => unwrap<Exam & { papers: Paper[] }>(http.get(`/exams/${id}`)),
  updateStatus: (id: number, status: string) =>
    unwrap<Exam>(http.patch(`/exams/${id}/status`, { status })),
  createPaper: (examId: number, data: Record<string, unknown>) =>
    unwrap<Paper>(http.post(`/exams/${examId}/papers`, data)),
  paper: (id: number) =>
    unwrap<Paper & { questions?: Question[]; actual_score?: number }>(http.get(`/papers/${id}`)),
  addQuestion: (paperId: number, data: Record<string, unknown>) =>
    unwrap<Question>(http.post(`/papers/${paperId}/questions`, data)),
  finalizePaper: (paperId: number) =>
    unwrap<Paper>(http.patch(`/papers/${paperId}/finalize`)),
}

export const scanApi = {
  batches: (paper_id?: number) =>
    unwrap<ScanBatch[]>(http.get('/scans/batches', { params: { paper_id } })),
  createBatch: (data: { paper_id: number; file_name?: string; page_count?: number }) =>
    unwrap<ScanBatch>(http.post('/scans/batches', data)),
  split: (batchId: number) => unwrap<ScanBatch>(http.patch(`/scans/batches/${batchId}/split`)),
  pages: (batchId: number) =>
    unwrap<Array<{ id: number; batch_id: number; page_index: number; cos_url?: string | null }>>(
      http.get(`/scans/batches/${batchId}/pages`),
    ),
  assign: (batchId: number, class_id?: number) =>
    unwrap<{ batch_id: number; created: number; total: number }>(
      http.post(`/scans/batches/${batchId}/assign`, { class_id }),
    ),
  confirm: (batchId: number) => unwrap<ScanBatch>(http.patch(`/scans/batches/${batchId}/confirm`)),
}

export const gradingApi = {
  queue: (paperId: number) =>
    unwrap<Submission[]>(http.get(`/grading/papers/${paperId}/submissions`)),
  detail: (submissionId: number) => unwrap<SubmissionDetail>(http.get(`/grading/submissions/${submissionId}`)),
  score: (submissionId: number, questionId: number, score: number) =>
    unwrap<AnswerScore>(http.put(`/grading/submissions/${submissionId}/questions/${questionId}`, { score })),
  finalize: (submissionId: number) =>
    unwrap<Submission>(http.post(`/grading/submissions/${submissionId}/finalize`)),
}

export const statsApi = {
  paperSummary: (paperId: number) =>
    unwrap<PaperSummary>(http.get(`/stats/papers/${paperId}/summary`)),
  paperByClass: (paperId: number) =>
    unwrap<Array<Record<string, unknown>>>(http.get(`/stats/papers/${paperId}/classes`)),
  paperByQuestion: (paperId: number) =>
    unwrap<Array<Record<string, unknown>>>(http.get(`/stats/papers/${paperId}/questions`)),
}

export { setAuthResolver }
export type { AuthResolver } from './http'
