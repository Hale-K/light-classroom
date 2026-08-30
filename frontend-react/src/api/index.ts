/**
 * 各业务模块 API（对接 FastAPI 后端 /api/v1 真实端点）。
 * 返回类型从 @/types 复用；数据由 http 拦截器解包为业务 data。
 */
import { http, unwrap, setAuthResolver } from './http'
import type {
  AdminSchool,
  AnswerScore,
  AutoClassAssignmentResult,
  ClassInfo,
  Campus,
  Building,
  Exam,
  ExamCandidateAssignment,
  ExamInvigilatorEntry,
  ExamPlan,
  ExamRoomEntry,
  ExamScheduleEntry,
  ExamVenuePlan,
  ExamSchedulingConfig,
  Grade,
  FacilityOverview,
  MeetingRecord,
  MenuResult,
  OrganizationTreeResult,
  OrganizationUnit,
  Paper,
  PaperSummary,
  PlatformAdminInfo,
  PermissionGroup,
  Question,
  RoleInfo,
  RoleMembersResult,
  RoomResource,
  ResourceAllocationRule,
  AllocationPreviewResult,
  ScanBatch,
  ScheduleEntry,
  ScheduleStrategyOption,
  ScheduleValidationResult,
  ScheduleVersionSummary,
  SchedulingResources,
  SeatArrangement,
  SeatEntry,
  StaffAccount,
  StaffAppointment,
  StaffDirectory,
  StaffRoleCode,
  Student,
  Submission,
  SubmissionDetail,
  UserInfo,
} from '@/types'

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

export interface AcademicYearEntry {
  entry_year: number
  cohort_label: string
  grade_years: { 高一: string; 高二: string; 高三: string }
  status: 'active' | 'inactive'
}
export interface AcademicYearsSettings {
  years: AcademicYearEntry[]
  current_entry_year: number | null
  current_academic_year: string | null
  current_term: '1' | '2'
}
export interface AcademicYearRolloverPreview {
  source_entry_year: number
  source_cohort_label: string
  target_entry_year: number
  target_cohort_label: string
  source_academic_year: string
  target_academic_year: string
  class_count: number
  student_count: number
  promote_high_one_classes: number
  promote_high_two_classes: number
  graduate_high_three_classes: number
  already_done: boolean
  warnings: string[]
}

export const authApi = {
  login: (phone: string, password: string) =>
    unwrap<LoginResult>(http.post('/auth/login', { phone, password })),
  register: (data: { name: string; phone: string; password: string; role?: string }) =>
    unwrap<UserInfo>(http.post('/auth/register', data)),
  me: () => unwrap<UserInfo>(http.get('/auth/me')),
  menus: () => unwrap<MenuResult>(http.get('/auth/menus')),
  school: () => unwrap<SchoolSettings>(http.get('/auth/school')),
  updateSchool: (data: {
    province?: string
    gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
  }) => unwrap<SchoolSettings>(http.patch('/auth/school', data)),
  academicYears: () => unwrap<AcademicYearsSettings>(http.get('/auth/academic-years')),
  previewAcademicYearRollover: (source_entry_year: number) =>
    unwrap<AcademicYearRolloverPreview>(http.post('/auth/academic-year-rollover/preview', { source_entry_year })),
  commitAcademicYearRollover: (source_entry_year: number) =>
    unwrap<{ current_entry_year: number; current_academic_year: string; current_term: '1' | '2'; promoted_student_count: number; created_class_count: number }>(
      http.post('/auth/academic-year-rollover/commit', { source_entry_year }),
    ),
  saveAcademicYears: (years: Array<{ entry_year: number; status: 'active' | 'inactive' }>, current_entry_year?: number | null, current_academic_year?: string | null, current_term?: '1' | '2') =>
    unwrap<AcademicYearsSettings>(http.put('/auth/academic-years', { years, current_entry_year, current_academic_year, current_term })),
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
  }) => unwrap<AdminSchool>(http.put(`/admin/schools/${id}`, data)),
  resetPassword: (id: number, password: string) =>
    unwrap<{ school_id: number; phone: string | null }>(
      http.post(`/admin/schools/${id}/reset-password`, { password }),
    ),
  schoolStats: () => unwrap<{ total: number }>(http.get('/admin/schools/stats')),
}

export const orgApi = {
  grades: async () => {
    const grades = await unwrap<Grade[]>(http.get('/org/grades'))
    // 年级按校区隔离；同一学校可能有多个校区的高一，必须保留校区名避免下拉框出现两个相同的“一年级”。
    return grades.map((grade) => {
      const plainName = grade.name.replace(/^.*[·•]\s*/, '')
      return { ...grade, name: grade.campus_name ? `${grade.campus_name} · ${plainName}` : plainName }
    })
  },
  createGrade: (data: { name: string; level: number; campus_id?: number | null }) =>
    unwrap<Grade>(http.post('/org/grades', data)),
  classes: (params?: { grade_id?: number }) =>
    unwrap<ClassInfo[]>(http.get('/org/classes', { params })),
  assignHeadTeacher: (classId: number, data: { teacher_id: number; academic_year: string; term: string }) =>
    unwrap<ClassInfo>(http.patch(`/org/classes/${classId}/head-teacher`, data)),
  createClass: (data: { grade_id: number; name: string; home_room_id?: number; class_type?: string; planned_student_count?: number; head_teacher_id?: number }) =>
    unwrap<ClassInfo>(http.post('/org/classes', data)),
  updateClassResourcePlan: (id: number, data: { home_room_id: number | null; class_type: string }) =>
    unwrap<ClassInfo>(http.patch(`/org/classes/${id}/resource-plan`, data)),
  autoAssignPreview: (data: { grade_id: number; class_ids: number[]; strategy: string; paper_id?: number; balance_gender?: boolean; overwrite_existing?: boolean }) =>
    unwrap<AutoClassAssignmentResult>(http.post('/org/classes/auto-assign/preview', data)),
  autoAssign: (data: { grade_id: number; class_ids: number[]; strategy: string; paper_id?: number; balance_gender?: boolean; overwrite_existing?: boolean }) =>
    unwrap<AutoClassAssignmentResult>(http.post('/org/classes/auto-assign', data)),
  students: (class_id?: number, campus_id?: number, grade_id?: number) =>
    unwrap<Student[]>(http.get('/org/students', { params: { class_id, campus_id, grade_id } })),
  validateStudentImport: (importType: 'full' | 'incremental', file: File) => {
    const body = new FormData()
    body.append('file', file)
    return unwrap<{
      token: string
      import_type: 'full' | 'incremental'
      total: number
      valid: number
      errors: Array<{ row: number; student_no: string; name: string; errors: string[] }>
      context: { entry_year: number; academic_year: string; term: string }
    }>(http.post(`/org/students/import/validate?import_type=${importType}`, body))
  },
  confirmStudentImport: (token: string) =>
    unwrap<{ task_id: string; status: string; processed: number; total: number; success: number; failed: number }>(
      http.post('/org/students/import/confirm', { token }),
    ),
  studentImportTask: (taskId: string) =>
    unwrap<{ task_id: string; status: string; processed: number; total: number; success: number; failed: number; errors?: Array<{ row: number; error: string }> }>(
      http.get(`/org/students/import/tasks/${taskId}`),
    ),
  createStudent: (data: Record<string, unknown>) =>
    unwrap<Student>(http.post('/org/students', data)),
  assignStudents: (student_ids: number[], class_id: number | null) =>
    unwrap<{ updated: number; class_id: number | null }>(
      http.patch('/org/students/assign-class', { student_ids, class_id }),
    ),
  updateStudentStatus: (student_id: number, status: string) =>
    unwrap<Student>(http.patch(`/org/students/${student_id}`, { status })),
  studentCount: () => unwrap<{ total: number }>(http.get('/org/students/count')),
  studentGradeMemberships: (params?: { academic_year?: string; grade_unit_id?: number; grade_id?: number }) =>
    unwrap<import('@/types').StudentGradeMembership[]>(http.get('/org/student-grade-memberships', { params })),
}

export const staffApi = {
  list: () => unwrap<StaffDirectory>(http.get('/staff')),
  create: (data: { name: string; phone: string; password: string; roles: StaffRoleCode[]; teacher_level?: string }) =>
    unwrap<StaffAccount>(http.post('/staff', data)),
  update: (id: number, data: { name: string; phone: string; roles: StaffRoleCode[]; teacher_level?: string | null }) =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}`, data)),
  updateRoles: (id: number, roles: StaffRoleCode[]) =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/roles`, { roles })),
  updateStatus: (id: number, status: 'active' | 'disabled') =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/status`, { status })),
}

export const organizationApi = {
  tree: () => unwrap<OrganizationTreeResult>(http.get('/organization/tree')),
  createUnit: (data: {
    name: string
    unit_type: OrganizationUnit['unit_type']
    parent_id?: number
    academic_year?: string
    cohort_label?: string
    grade_id?: number | null
    sort_order?: number
  }) => unwrap<OrganizationUnit>(http.post('/organization/units', data)),
  updateUnit: (id: number, data: Partial<Pick<OrganizationUnit,
    'name' | 'parent_id' | 'academic_year' | 'cohort_label' | 'grade_id' | 'sort_order' | 'status'
  >>) => unwrap<OrganizationUnit>(http.patch(`/organization/units/${id}`, data)),
  gradeCenter: () =>
    unwrap<{ unit_id: number | null; unit_name: string | null }>(http.get('/organization/grade-center')),
  setGradeCenter: (unitId: number) =>
    unwrap<{ unit_id: number; unit_name: string }>(http.put(`/organization/grade-center/${unitId}`)),
  appointments: (includeArchived = false) => unwrap<StaffAppointment[]>(http.get('/organization/appointments', { params: { include_archived: includeArchived } })),
  createAppointment: (data: {
    organization_unit_id: number
    staff_id: number
    position_code: StaffAppointment['position_code']
    academic_year?: string
    replace_grade_assignment?: boolean
  }) => unwrap<StaffAppointment>(http.post('/organization/appointments', data)),
  autoAllocateAppointments: (data: {
    target_unit_id: number
    academic_year?: string
    position_code: StaffAppointment['position_code']
    plans: Array<{ source_unit_id: number; teacher_ids: number[]; required_count: number }>
  }) => unwrap<{ created_count: number; target_unit_id: number }>(http.post('/organization/appointments/auto-allocate', data)),
  deleteAppointment: (id: number) =>
    unwrap<{ id: number }>(http.delete(`/organization/appointments/${id}`)),
  archiveUnitAppointments: (unitId: number) =>
    unwrap<{ unit_id: number; archived_count: number }>(http.post(`/organization/appointments/archive-by-unit/${unitId}`)),
}

export const facilityApi = {
  overview: () => unwrap<FacilityOverview>(http.get('/facilities/overview')),
  createCampus: (data: { name: string; address?: string; student_capacity?: number }) =>
    unwrap<Campus>(http.post('/facilities/campuses', data)),
  createBuilding: (data: { campus_id: number; name: string; code?: string; floor_count: number }) =>
    unwrap<Building>(http.post('/facilities/buildings', data)),
  updateBuildingStatus: (id: number, status: 'active' | 'maintenance' | 'disabled') =>
    unwrap<Building>(http.patch(`/facilities/buildings/${id}/status`, { status })),
  rooms: (params?: { building_id?: number; room_type?: RoomResource['room_type']; keyword?: string }) =>
    unwrap<RoomResource[]>(http.get('/facilities/rooms', { params })),
  createRoom: (data: {
    building_id: number
    name: string
    code?: string
    floor: number
    capacity: number
    room_type: RoomResource['room_type']
    features: string[]
    is_schedulable: boolean
    is_exam_enabled: boolean
    is_meeting_enabled: boolean
  }) => unwrap<RoomResource>(http.post('/facilities/rooms', data)),
  allocationRules: () => unwrap<ResourceAllocationRule[]>(http.get('/facilities/allocation-rules')),
  previewAllocationRule: (data: Record<string, unknown>) =>
    unwrap<AllocationPreviewResult>(http.post('/facilities/allocation-rules/preview', data)),
  createAllocationRule: (data: Record<string, unknown>) =>
    unwrap<ResourceAllocationRule>(http.post('/facilities/allocation-rules', data)),
  deleteAllocationRule: (id: number) => unwrap<null>(http.delete(`/facilities/allocation-rules/${id}`)),
  classPlanningPreview: (data: {
    grade_id: number
    grade_group_id?: number
    elite_count: number
    key_count: number
    experimental_count: number
    regular_count: number
    strategy: 'random' | 'snake' | 'custom'
    custom_room_ids?: number[]
    custom_sub_strategy?: 'random' | 'snake'
    building_preferences?: Array<{ building_id: number; preferred_types: string[] }>
    skip_generated?: boolean
    inspect_only?: boolean
  }) => unwrap<{
    grade_id: number
    grade_group_id: number | null
    cohort_label: string | null
    grade_name: string
    grade_label: string
    existing_count: number
    available_room_count: number
    requested_total: number
    item_count: number
    items: Array<{
      room_id: number
      room_name: string
      building_id: number
      building_name: string
      floor: number
      code: string | null
      capacity: number
      sequence_no: number
      class_type: string
      proposed_class_name: string
    }>
    remaining_pools: { elite: number; key: number; experimental: number; regular: number }
    student_count: number
    assigned_student_count: number
    remaining_student_count: number
    available_capacity: number
    capacity_sufficient: boolean
    capacity_gap: number
    recommended_class_count: number
  }>(http.post('/facilities/class-planning/preview', data)),
  classPlanningExecute: (data: {
    grade_id: number
    grade_group_id?: number
    elite_count: number
    key_count: number
    experimental_count: number
    regular_count: number
    strategy: 'random' | 'snake' | 'custom'
    custom_room_ids?: number[]
    custom_sub_strategy?: 'random' | 'snake'
    building_preferences?: Array<{ building_id: number; preferred_types: string[] }>
    skip_generated?: boolean
    inspect_only?: boolean
    plan?: Array<{
      room_id: number
      room_name: string
      building_id: number
      building_name: string
      floor: number
      code: string | null
      capacity: number
      sequence_no: number
      class_type: string
      proposed_class_name: string
    }>
  }) => unwrap<{
    created_count: number
    by_type: Record<string, number>
    class_ids: number[]
  }>(http.post('/facilities/class-planning/execute', data)),
  meetings: () => unwrap<MeetingRecord[]>(http.get('/meetings')),
  createMeeting: (data: {
    title: string
    room_id: number
    start_at: string
    end_at: string
    participant_ids?: number[]
    agenda?: string
  }) => unwrap<MeetingRecord>(http.post('/meetings', data)),
}

export const schedulingApi = {
  resources: () => unwrap<SchedulingResources>(http.get('/scheduling/resources')),
  subjects: () => unwrap<import('@/types').SubjectInfo[]>(http.get('/scheduling/subjects')),
  courseHours: (params: { academic_year: string; term: string; class_id?: number }) =>
    unwrap<import('@/types').CourseHourPlanInfo[]>(http.get('/scheduling/course-hours', { params })),
  saveCourseHour: (data: {
      id?: number
      class_id: number
      subject_id: number
      academic_year: string
      term: string
      weekday_periods: number
      saturday_periods: number
      weekly_periods: number
      week_parity: import('@/types').WeekParity
      evening_periods_odd: number
      evening_periods_even: number
  }) => unwrap<import('@/types').CourseHourPlanInfo>(http.post('/scheduling/course-hours', data)),
  deleteCourseHour: (id: number) => unwrap<null>(http.delete(`/scheduling/course-hours/${id}`)),
  gridConfig: (params: { academic_year: string; term: string }) =>
    unwrap<import('@/types').SchedulingGridConfig>(http.get('/scheduling/grid-config', { params })),
  saveGridConfig: (data: import('@/types').SchedulingGridConfig & { academic_year: string; term: string }) =>
    unwrap<import('@/types').SchedulingGridConfig>(http.put('/scheduling/grid-config', data)),
  strategies: () => unwrap<ScheduleStrategyOption[]>(http.get('/scheduling/strategies')),
  createTeacher: (data: { name: string; phone: string; password: string }) =>
    unwrap(http.post('/scheduling/teachers', data)),
  createSubject: (name: string, eveningStudyAllowed = false, courseType: 'subject' | 'activity' = 'subject') => unwrap<import('@/types').SubjectInfo>(http.post('/scheduling/subjects', { name, course_type: courseType, evening_study_allowed: eveningStudyAllowed })),
  updateSubject: (id: number, data: { name: string; course_type: 'subject' | 'activity'; evening_study_allowed: boolean }) => unwrap<import('@/types').SubjectInfo>(http.put(`/scheduling/subjects/${id}`, data)),
  saveAssignment: (data: {
    teacher_id?: number
    subject_id?: number
    class_id: number
    academic_year: string
    term: string
    weekly_periods: number
    room?: string
  }) => unwrap(http.post('/scheduling/assignments', data)),
  deleteAssignment: (id: number) => unwrap(http.delete(`/scheduling/assignments/${id}`)),
  scopeRules: (params: { academic_year: string; term: string }) =>
    unwrap<import('@/types').TeacherScopeRule[]>(http.get('/scheduling/teacher-scope-rules', { params })),
  saveScopeRules: (data: { academic_year: string; term: string; rules: import('@/types').TeacherScopeRule[] }) =>
    unwrap<import('@/types').TeacherScopeRule[]>(http.put('/scheduling/teacher-scope-rules', data)),
  autoTeaching: (data: { academic_year: string; term: string; class_ids?: number[]; subject_id?: number; weekly_periods: number; max_weekly_periods: number; subject_period_rules?: Array<{ subject_id: number; weekly_periods: number }>; subject_teacher_limits?: Array<{ subject_id: number; max_weekly_periods: number }>; execute?: boolean; days?: number; periods_per_day?: number; forbidden_slots?: Array<[number, number]>; max_class_lessons_per_day?: number; max_teacher_lessons_per_day?: number; max_same_subject_per_day?: number }) =>
    unwrap<{ created: Array<{ teacher_id: number; subject_id: number; class_id: number; weekly_periods: number; student_count?: number; suggested_weekly_periods?: number }>; skipped: Array<{ class_id: number; subject_id: number; reason: string }>; created_count: number; skipped_count: number; updated_count: number; executed: boolean; workload_summary: Array<{ teacher_id: number; teacher_name?: string; weekly_periods: number; max_weekly_periods: number; sufficient: boolean }>; plan: Array<{ teacher_id?: number; subject_id: number; class_id: number; weekly_periods?: number; student_count?: number; suggested_weekly_periods?: number; teacher_name?: string; subject_name?: string; class_name?: string; reason?: string; status: 'success' | 'skipped' }>; time_structure: { days: number; periods_per_day: number; forbidden_slots: Array<[number, number]>; max_class_lessons_per_day?: number; max_teacher_lessons_per_day?: number; max_same_subject_per_day?: number; weekly_lesson_cap: number; same_subject_weekly_cap?: number; teacher_weekly_cap?: number } }>(http.post('/scheduling/auto-teaching', data)),
  generate: (data: {
    academic_year: string
    term: string
    class_ids?: number[]
    days?: number
    periods_per_day?: number
    forbidden_slots?: Array<[number, number]>
    max_class_lessons_per_day?: number
    max_teacher_lessons_per_day?: number
    max_class_lessons_on_saturday?: number
    max_teacher_lessons_on_saturday?: number
    max_pe_teacher_lessons_per_day?: number
    enable_evening?: boolean
    evening_start_period?: number | null
    evening_daily_periods_odd?: number[]
    evening_daily_periods_even?: number[]
    evening_subject_ids?: number[]
    max_teacher_weekly_periods?: number
    max_same_subject_per_day?: number
    require_full_week?: boolean
    avoid_consecutive_teacher_lessons?: boolean
    strategy_codes?: string[]
  }) =>
    unwrap<{
      created: number
      class_count: number
    unplaced: Array<{ assignment_id: number; count: number }>
      can_rollback: boolean
    }>(http.post('/scheduling/generate', data)),
  adjustmentOptions: (params: { schedule_id: number; academic_year: string; term: string; days?: number; periods_per_day?: number }) =>
    unwrap<Array<{ weekday: number; period: number; available: boolean; reason: string }>>(
      http.get('/scheduling/adjustments/options', { params }),
    ),
  moveSchedule: (data: { schedule_id: number; target_weekday: number; target_period: number; academic_year: string; term: string; days?: number; periods_per_day?: number }) =>
    unwrap<{ id: number; weekday: number; period: number }>(http.post('/scheduling/adjustments', data)),
  substitutes: (params: { schedule_id: number; academic_year: string; term: string }) =>
    unwrap<Array<{ teacher_id: number; teacher_name: string; weekly_lessons: number; available: boolean; reason: string }>>(
      http.get('/scheduling/substitutes', { params }),
    ),
  substituteSchedule: (data: { schedule_id: number; teacher_id: number; academic_year: string; term: string }) =>
    unwrap<{ id: number; teacher_id: number }>(http.post('/scheduling/substitutes', data)),
  rollback: () =>
    unwrap<{ restored: number; academic_year: string; term: string }>(http.post('/scheduling/rollback')),
  listVersions: () =>
    unwrap<ScheduleVersionSummary[]>(http.get('/scheduling/versions')),
  restoreVersion: (version_id: number) =>
    unwrap<{ restored: number; academic_year: string; term: string; version_id: number }>(http.post(`/scheduling/versions/${version_id}/restore`)),
  validate: (data: {
    academic_year: string
    term: string
    class_ids?: number[]
    days?: number
    periods_per_day?: number
    forbidden_slots?: Array<[number, number]>
    max_class_lessons_per_day?: number
    max_teacher_lessons_per_day?: number
    max_class_lessons_on_saturday?: number
    max_teacher_lessons_on_saturday?: number
    max_pe_teacher_lessons_per_day?: number
    enable_evening?: boolean
    evening_start_period?: number | null
    evening_daily_periods_odd?: number[]
    evening_daily_periods_even?: number[]
    evening_subject_ids?: number[]
    max_teacher_weekly_periods?: number
    max_same_subject_per_day?: number
    require_full_week?: boolean
    avoid_consecutive_teacher_lessons?: boolean
    strategy_codes?: string[]
  }) => unwrap<ScheduleValidationResult>(http.post('/scheduling/validate', data)),
  weekly: (params: { class_id: number; academic_year: string; term: string }) =>
    unwrap<ScheduleEntry[]>(http.get('/scheduling/weekly', { params })),
  calendar: (params: { class_id: number; academic_year: string; term: string; week_start: string }) =>
    unwrap<ScheduleEntry[]>(http.get('/scheduling/calendar', { params })),
}

export interface GaokaoOverview {
  scheme: {
    id: number
    name: string
    mode: '3+1+2' | '3+3' | 'traditional'
    entry_year: number
  } | null
  workflow: {
    code: 'exploration' | 'intention' | 'effective'
    label: string
    description: string
    can_generate_teaching_classes: boolean
    can_generate_schedule: boolean
  } | null
  workflow_warnings: string[]
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
    walk_student_count: number
    delivery_mode: 'administrative' | 'teaching_class'
    recommended_class_count: number
    teaching_class_count: number
    teacher_count: number
  }>
}

export const gaokaoApi = {
  overview: (params: { academic_year: string; term: string; grade_id?: number }) =>
    unwrap<GaokaoOverview>(http.get('/gaokao/overview', { params })),
  generateTeachingClasses: (data: {
    grade_id: number
    academic_year: string
    term: string
    capacity?: number
    weekly_periods?: number
    primary_delivery_mode?: 'administrative' | 'teaching_class'
  }) =>
    unwrap<{ created: number; memberships: number }>(
      http.post('/gaokao/teaching-classes/generate', data),
    ),
  generateSchedule: (data: {
    grade_id: number
    academic_year: string
    term: string
    days?: number
    periods_per_day?: number
  }) =>
    unwrap<{ created: number; unplaced: Array<{ teaching_class_id: number; count: number }> }>(
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
    order: string
    layout: string
    pairing?: string
    seed?: number
    exam_id?: number
    front_student_ids?: number[]
    separation_pairs?: number[][]
    adjacency_pairs?: number[][]
    effective_from?: string
    effective_to?: string
  }) => unwrap<SeatArrangement>(http.post('/seating/generate', data)),
  activate: (id: number) =>
    unwrap<SeatArrangement>(http.patch(`/seating/arrangements/${id}/activate`)),
  updateSeats: (id: number, seats: SeatEntry[]) =>
    unwrap<SeatArrangement>(http.patch(`/seating/arrangements/${id}/seats`, { seats })),
}

export const examSchedulingApi = {
  get: (examId: number) => unwrap<ExamScheduleEntry[]>(http.get(`/exam-scheduling/${examId}`)),
  generate: (data: {
    exam_id: number
    start_date: string
    room: string
    sessions: Array<{ start_time: string; end_time: string }>
    excluded_dates?: string[]
    grade_ids?: number[]
    rooms?: Array<{ name: string; capacity: number }>
  }) => unwrap<ExamScheduleEntry[]>(http.post('/exam-scheduling/generate', data)),
  rooms: (params: { keyword?: string; page?: number; page_size?: number } = {}) =>
    unwrap<{
      items: ExamRoomEntry[]
      pagination: { page: number; page_size: number; total: number; total_pages: number }
    }>(http.get('/exam-scheduling/rooms', { params })),
  createRoom: (data: { name: string; capacity: number; building?: string; room_type: string }) =>
    unwrap<ExamRoomEntry>(http.post('/exam-scheduling/rooms', data)),
  updateRoom: (id: number, data: { name?: string; capacity?: number; building?: string; room_type?: string }) =>
    unwrap<ExamRoomEntry>(http.patch(`/exam-scheduling/rooms/${id}`, data)),
  deleteRoom: (id: number) => unwrap<{ id: number }>(http.delete(`/exam-scheduling/rooms/${id}`)),
  venues: (examId: number) =>
    unwrap<ExamVenuePlan>(http.get(`/exam-scheduling/exams/${examId}/venues`)),
  saveVenues: (examId: number, rooms: ExamVenuePlan['rooms']) =>
    unwrap<ExamVenuePlan>(http.put(`/exam-scheduling/exams/${examId}/venues`, { rooms })),
  plan: (examId: number) => unwrap<ExamPlan>(http.get(`/exam-scheduling/plans/${examId}`)),
  generatePlan: (data: {
    exam_id: number
    start_date: string
    room: string
    sessions: Array<{ start_time: string; end_time: string }>
    excluded_dates?: string[]
    grade_ids?: number[]
    invigilators_per_room?: number
  }) => unwrap<ExamPlan>(http.post('/exam-scheduling/plans', data)),
  candidates: (examId: number, params: { keyword?: string; room_assignment_id?: number; grade_id?: number; subject_id?: number; exam_date?: string; page?: number; page_size?: number } = {}) =>
    unwrap<{
      items: ExamCandidateAssignment[]
      pagination: { page: number; page_size: number; total: number; total_pages: number }
    }>(http.get(`/exam-scheduling/plans/${examId}/candidates`, { params })),
  config: (examId: number) => unwrap<ExamSchedulingConfig>(http.get(`/exam-scheduling/exams/${examId}/config`)),
  saveConfig: (examId: number, data: Omit<ExamSchedulingConfig, 'exam_id'>) =>
    unwrap<ExamSchedulingConfig>(http.put(`/exam-scheduling/exams/${examId}/config`, data)),
  invigilators: (examId: number) => unwrap<ExamInvigilatorEntry[]>(http.get(`/exam-scheduling/exams/${examId}/invigilators`)),
  saveInvigilator: (examId: number, teacherId: number, data: { enabled: boolean; leave_start?: string | null; leave_end?: string | null; unavailable_slots?: string[]; note?: string | null }) =>
    unwrap<{ teacher_id: number }>(http.put(`/exam-scheduling/exams/${examId}/invigilators/${teacherId}`, data)),
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
  finalizePaper: (paperId: number) => unwrap<Paper>(http.patch(`/papers/${paperId}/finalize`)),
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
  detail: (submissionId: number) =>
    unwrap<SubmissionDetail>(http.get(`/grading/submissions/${submissionId}`)),
  score: (submissionId: number, questionId: number, score: number) =>
    unwrap<AnswerScore>(
      http.put(`/grading/submissions/${submissionId}/questions/${questionId}`, { score }),
    ),
  finalize: (submissionId: number) =>
    unwrap<Submission>(http.post(`/grading/submissions/${submissionId}/finalize`)),
}

export interface DashboardSummary {
  exams: Array<
    Exam & { paper_count: number; ongoing: boolean }
  >
  ongoing_count: number
  papers: Array<{
    id: number
    title: string
    subject_id: number
    graded: number
    total: number
  }>
  paper_count: number
  graded_total: number
  submission_total: number
  batches: ScanBatch[]
  pending_batch_count: number
}

export const dashboardApi = {
  summary: () => unwrap<DashboardSummary>(http.get('/dashboard/summary')),
}

export const statsApi = {
  paperSummary: (paperId: number) =>
    unwrap<PaperSummary>(http.get(`/stats/papers/${paperId}/summary`)),
  paperByClass: (paperId: number) =>
    unwrap<Array<Record<string, unknown>>>(http.get(`/stats/papers/${paperId}/classes`)),
  paperByQuestion: (paperId: number) =>
    unwrap<Array<Record<string, unknown>>>(http.get(`/stats/papers/${paperId}/questions`)),
}

/** 角色与权限（RBAC） */
export const rbacApi = {
  /** 权限点目录（按模块分组） */
  permissions: () => unwrap<PermissionGroup[]>(http.get('/rbac/permissions')),
  /** 角色列表 */
  roles: () => unwrap<RoleInfo[]>(http.get('/rbac/roles')),
  /** 新建角色 */
  createRole: (data: { code: string; name: string; description?: string }) =>
    unwrap<{ id: number; code: string; name: string }>(http.post('/rbac/roles', data)),
  /** 编辑角色（名称/说明） */
  updateRole: (id: number, data: { name: string; description?: string }) =>
    unwrap<{ id: number; name: string; description: string }>(
      http.patch(`/rbac/roles/${id}`, data),
    ),
  /** 删除角色 */
  deleteRole: (id: number) => unwrap<null>(http.delete(`/rbac/roles/${id}`)),
  /** 角色已拥有的权限点编码 */
  rolePermissions: (roleId: number) =>
    unwrap<string[]>(http.get(`/rbac/roles/${roleId}/permissions`)),
  /** 整量设置角色的权限点 */
  setRolePermissions: (roleId: number, permissions: string[]) =>
    unwrap<string[]>(http.put(`/rbac/roles/${roleId}/permissions`, { permissions })),
  /** 角色成员候选及当前分配状态 */
  roleMembers: (roleId: number) =>
    unwrap<RoleMembersResult>(http.get(`/rbac/roles/${roleId}/members`)),
  /** 整量设置角色成员，不影响这些人员的其他角色 */
  setRoleMembers: (roleId: number, userIds: number[]) =>
    unwrap<number[]>(http.put(`/rbac/roles/${roleId}/members`, { user_ids: userIds })),
}

/** 教师档案 */
export const teacherProfilesApi = {
  /** 筛选条件默认值 + 年级候选 */
  filters: () =>
    unwrap<import('@/types').TeacherProfileFiltersMeta>(
      http.get('/teacher-profiles/filters'),
    ),
  /** 教师档案列表 */
  list: (params: {
    only_head_teacher?: boolean
    subject_id?: number | null
    grade_id?: number | null
    cohort_entry_year?: number | null
    academic_year?: string | null
    term?: string
    keyword?: string | null
  }) =>
    unwrap<import('@/types').TeacherProfileListResult>(
      http.get('/teacher-profiles', { params }),
    ),
  /** 教师个人周课表 */
  weeklySchedule: (teacherId: number, params: { academic_year?: string | null; term?: string } = {}) =>
    unwrap<import('@/types').TeacherWeeklyScheduleResult>(
      http.get(`/teacher-profiles/${teacherId}/weekly-schedule`, { params }),
    ),
}

export { setAuthResolver }
export type { AuthResolver } from './http'
