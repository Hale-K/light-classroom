/**
 * 各业务模块 API（对接 FastAPI 后端 /api/v1 真实端点）。
 * 返回类型从 @/types 复用；数据由 http 拦截器解包为业务 data。
 */
import { ApiError, http, unwrap, setAuthResolver } from './http'
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
  MenuPermissionBinding,
  PermissionGroup,
  RoleMenuPreview,
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
  SchedulingRuleGroup,
  SchedulingRuleGroupCatalog,
  SchedulingRuleValidationResult,
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
    unwrap<{ access_token: string; token_type: string; admin: PlatformAdminInfo }>(
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
  toggleAdminStatus: (id: number) =>
    unwrap<{ school_id: number; frozen: boolean }>(
      http.post(`/admin/schools/${id}/admin-status`),
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
  simulateStudents: (data: { cohort_label: string; grade_id: number; male_count: number; female_count: number }) =>
    unwrap<{
      created: number
      male_count: number
      female_count: number
      cohort_label: string
      grade_id: number
      grade_name: string
      academic_year: string
      status: string
    }>(http.post('/org/students/simulate', data)),
  assignStudents: (student_ids: number[], class_id: number | null) =>
    unwrap<{ updated: number; class_id: number | null }>(
      http.patch('/org/students/assign-class', { student_ids, class_id }),
    ),
  updateStudentStatus: (student_id: number, status: string) =>
    unwrap<Student>(http.patch(`/org/students/${student_id}`, { status })),
  studentCount: () => unwrap<{ total: number }>(http.get('/org/students/count')),
  provisionStudentAccounts: (data: { grade_id: number; initial_password: string }) =>
    unwrap<{ created: number; reset: number; skipped: number; total: number; login_prefix: string }>(
      http.post('/student-auth/accounts/provision', data),
    ),
  studentGradeMemberships: (params?: { academic_year?: string; grade_unit_id?: number; grade_id?: number }) =>
    unwrap<import('@/types').StudentGradeMembership[]>(http.get('/org/student-grade-memberships', { params })),
}

export const staffApi = {
  list: () => unwrap<StaffDirectory>(http.get('/staff')),
  create: (data: { name: string; phone: string; password: string; roles: StaffRoleCode[]; teacher_level?: string; unit_ids?: number[] }) =>
    unwrap<StaffAccount>(http.post('/staff', data)),
  update: (id: number, data: { name: string; phone: string; roles: StaffRoleCode[]; teacher_level?: string | null }) =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}`, data)),
  updateRoles: (id: number, roles: StaffRoleCode[]) =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/roles`, { roles })),
  updateStatus: (id: number, status: 'active' | 'disabled') =>
    unwrap<StaffAccount>(http.patch(`/staff/${id}/status`, { status })),
  freeze: (id: number, reason: string) =>
    unwrap<StaffAccount>(http.post(`/staff/${id}/freeze`, { reason })),
  unfreeze: (id: number) =>
    unwrap<StaffAccount>(http.post(`/staff/${id}/unfreeze`)),
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
  appointments: () => unwrap<StaffAppointment[]>(http.get('/organization/appointments')),
  createAppointment: (data: {
    organization_unit_id: number
    staff_id: number
    position_code: StaffAppointment['position_code']
    academic_year?: string
    replace_grade_assignment?: boolean
  }) => unwrap<StaffAppointment>(http.post('/organization/appointments', data)),
  deleteAppointment: (id: number) =>
    unwrap<{ id: number }>(http.delete(`/organization/appointments/${id}`)),
  deleteUnit: (id: number) =>
    unwrap<{ id: number }>(http.delete(`/organization/units/${id}`)),
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
  createRoomsBatch: (data: {
    building_id: number
    floor: number
    count: number
    start_number: number
    name_prefix: string
    capacity: number
    multimedia: boolean
    is_schedulable: boolean
  }) => unwrap<{ created_count: number; skipped_count: number; skipped_names: string[] }>(http.post('/facilities/rooms/batch', data)),
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
      evening_parity?: import('@/types').EveningParity
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
  ruleGroup: (params: { academic_year: string; term: string; grade_id?: number; group_id?: string }) =>
    unwrap<SchedulingRuleGroup | null>(http.get('/scheduling/rule-group', { params })),
  ruleGroups: (params: { academic_year: string; term: string }) =>
    unwrap<SchedulingRuleGroupCatalog>(http.get('/scheduling/rule-groups', { params })),
  saveRuleGroup: (data: SchedulingRuleGroup) =>
    unwrap<{ group: SchedulingRuleGroup; compiler: Array<{ rule_id: string; code: string; status: 'ready' | 'unresolved'; reason?: string | null }> }>(
      http.put('/scheduling/rule-group', data),
    ),
  applyRuleSuggestion: (data: {
    academic_year: string
    term: string
    group_id: string
    suggestion: Record<string, unknown>
  }) =>
    unwrap<{
      note: string
      group: SchedulingRuleGroup
      compiler: Array<{ rule_id: string; code: string; status: 'ready' | 'unresolved'; reason?: string | null }>
    }>(http.post('/scheduling/rule-group/apply-suggestion', data)),
  saveRuleGroups: (data: { academic_year: string; term: string; active_id?: string | null; groups: SchedulingRuleGroup[] }) =>
    unwrap<SchedulingRuleGroupCatalog>(http.put('/scheduling/rule-groups', data)),
  verifySchedule: (data: {
    academic_year: string
    term: string
    class_id?: number
    grade_id?: number
    rule_group_id?: string
  }) =>
    unwrap<{
      rule_group_id: string
      rule_group_name: string
      grade_id: number | null
      class_count: number
      hard_failure_count: number
      soft_failure_count: number
      validation: SchedulingRuleValidationResult
    }>(http.post('/scheduling/verify-schedule', data)),
  autoTeaching: (data: { academic_year: string; term: string; class_ids?: number[]; subject_id?: number; weekly_periods: number; max_weekly_periods: number; subject_period_rules?: Array<{ subject_id: number; weekly_periods: number }>; subject_teacher_limits?: Array<{ subject_id: number; max_weekly_periods: number }>; execute?: boolean; days?: number; periods_per_day?: number; forbidden_slots?: Array<[number, number]>; max_class_lessons_per_day?: number; max_teacher_lessons_per_day?: number; max_same_subject_per_day?: number }) =>
    unwrap<{ created: Array<{ teacher_id: number; subject_id: number; class_id: number; weekly_periods: number; student_count?: number; suggested_weekly_periods?: number }>; skipped: Array<{ class_id: number; subject_id: number; reason: string }>; created_count: number; skipped_count: number; updated_count: number; executed: boolean; workload_summary: Array<{ teacher_id: number; teacher_name?: string; weekly_periods: number; max_weekly_periods: number; sufficient: boolean }>; plan: Array<{ teacher_id?: number; subject_id: number; class_id: number; weekly_periods?: number; student_count?: number; suggested_weekly_periods?: number; teacher_name?: string; subject_name?: string; class_name?: string; reason?: string; status: 'success' | 'skipped' }>; time_structure: { days: number; periods_per_day: number; forbidden_slots: Array<[number, number]>; max_class_lessons_per_day?: number; max_teacher_lessons_per_day?: number; max_same_subject_per_day?: number; weekly_lesson_cap: number; same_subject_weekly_cap?: number; teacher_weekly_cap?: number } }>(http.post('/scheduling/auto-teaching', data)),
  generate: (data: {
    academic_year: string
    term: string
    class_ids?: number[]
    rule_group_id?: string
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
    preview?: boolean
    locked_items?: Array<{
      assignment_id?: number
      class_id: number
      subject_id: number
      teacher_id?: number | null
      weekday: number
      period: number
      week_parity?: import('@/types').WeekParity
    }>
  }) =>
    unwrap<{
      created: number
      class_count: number
      unplaced: Array<{ assignment_id: number; count: number }>
      can_rollback: boolean
      preview?: boolean
      items?: Array<{
        assignment_id: number
        class_id: number
        weekday: number
        period: number
        subject_id: number
        teacher_id: number | null
        room?: string | null
        week_parity: import('@/types').WeekParity
      }>
      rule_validation?: SchedulingRuleValidationResult | null
    }>(http.post('/scheduling/generate', data, { timeout: 300000 })),
  startGenerateJob: (data: Record<string, unknown>) =>
    unwrap<{ job_id: string; resumed?: boolean }>(http.post('/scheduling/generate-jobs', data)),
  activeGenerateJob: (params: { academic_year: string; term: string }) =>
    unwrap<{
      job_id: string
      status: 'queued' | 'running' | 'retrying'
      stage: string
      message: string
      percent: number
      attempt: number
      created_at: string
      updated_at: string
      heartbeat_at: string
    } | null>(http.get('/scheduling/generate-jobs/active', { params })),
  streamGenerateJob: async (
    jobId: string,
    onEvent: (event: {
      type: string
      stage?: string
      message?: string
      percent?: number
      elapsed?: number
      solutions?: number
      phase?: string
      result?: {
        created: number
        class_count: number
        unplaced?: Array<{ assignment_id: number; count: number }>
      }
      detail?: unknown
    }) => void,
    signal?: AbortSignal,
  ) => {
    const { getAuthHeaders, getSseApiBaseURL } = await import('./http')
    let lastError: unknown = new ApiError('排课进度连接已中断', -1, 0)
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        const response = await fetch(`${getSseApiBaseURL()}/scheduling/generate-jobs/${jobId}/events`, {
          headers: {
            ...getAuthHeaders(),
            Accept: 'text/event-stream',
            'Cache-Control': 'no-cache',
          },
          cache: 'no-store',
          credentials: 'omit',
          signal,
        })
        if (!response.ok) {
          if (response.status === 401) {
            throw new ApiError('登录已失效，请重新登录', 401, 401)
          }
          throw new ApiError(`订阅生成进度失败（${response.status}）`, response.status, response.status)
        }
        if (!response.body) throw new ApiError('浏览器不支持流式响应', -1, 0)
        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        let currentEvent = 'message'
        let finished = false
        while (!finished) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const chunks = buffer.split(/\r?\n/)
          buffer = chunks.pop() || ''
          for (const line of chunks) {
            if (line.startsWith('event:')) {
              currentEvent = line.slice(6).trim()
              continue
            }
            if (!line.startsWith('data:')) continue
            const raw = line.slice(5).trim()
            if (!raw) continue
            const payload = JSON.parse(raw) as {
              type?: string
              stage?: string
              message?: string
              percent?: number
              elapsed?: number
              solutions?: number
              phase?: string
              result?: {
                created: number
                class_count: number
                unplaced?: Array<{ assignment_id: number; count: number }>
              }
              detail?: unknown
            }
            const type = payload.type || currentEvent
            onEvent({
              type,
              stage: payload.stage,
              message: payload.message,
              percent: payload.percent,
              elapsed: payload.elapsed,
              solutions: payload.solutions,
              phase: payload.phase,
              result: payload.result,
              detail: payload.detail,
            })
            currentEvent = 'message'
            if (type === 'done' || type === 'error') {
              finished = true
              break
            }
          }
        }
        if (finished) return
        lastError = new ApiError('排课进度连接已中断', -1, 0)
      } catch (error) {
        if (signal?.aborted) throw error
        if (error instanceof ApiError && error.status === 401) throw error
        lastError = error
      }
      await new Promise((resolve) => window.setTimeout(resolve, Math.min(5000, 750 * (attempt + 1))))
    }
    throw lastError
  },
  adjustmentOptions: (params: { schedule_id: number; academic_year: string; term: string; days?: number; periods_per_day?: number }) =>
    unwrap<Array<{
      weekday: number
      period: number
      week_parity?: 'all' | 'odd' | 'even'
      available: boolean
      selectable?: boolean
      reason: string
      mode?: 'move' | 'swap'
      checks?: Array<{ key: string; label: string; passed: boolean; severity?: string }>
      swap_schedule_id?: number | null
      swap_with_subject?: string | null
      swap_with_teacher?: string | null
    }>>(
      http.get('/scheduling/adjustments/options', { params }),
    ),
  previewAdjustment: (data: {
    schedule_id: number
    target_weekday: number
    target_period: number
    target_week_parity?: 'all' | 'odd' | 'even'
    academic_year: string
    term: string
    days?: number
    periods_per_day?: number
  }) =>
    unwrap<{
      weekday: number
      period: number
      week_parity?: 'all' | 'odd' | 'even'
      available: boolean
      selectable?: boolean
      reason: string
      mode?: 'move' | 'swap'
      checks: Array<{ key: string; label: string; passed: boolean; severity?: string }>
      swap_schedule_id?: number | null
      swap_with_subject?: string | null
      swap_with_teacher?: string | null
    }>(http.post('/scheduling/adjustments/preview', data)),
  moveSchedule: (data: {
    schedule_id: number
    target_weekday: number
    target_period: number
    target_week_parity?: 'all' | 'odd' | 'even'
    academic_year: string
    term: string
    days?: number
    periods_per_day?: number
    force?: boolean
  }) =>
    unwrap<{ id: number; weekday: number; period: number; mode?: string; forced?: boolean }>(
      http.post('/scheduling/adjustments', data),
    ),
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

export interface GaokaoChoiceReview {
  id: number
  student_id: number
  student_no: string
  student_name: string
  grade_id: number | null
  primary_subject_name: string
  secondary_subject_names: string[]
  status: 'draft' | 'confirmed' | 'rejected' | 'locked'
  round_no: number
}

export const gaokaoApi = {
  overview: (params: { academic_year: string; term: string; grade_id?: number }) =>
    unwrap<GaokaoOverview>(http.get('/gaokao/overview', { params })),
  choicesForReview: (params: { academic_year: string; term: string; grade_id?: number; status_filter?: string }) =>
    unwrap<GaokaoChoiceReview[]>(http.get('/gaokao/choices', { params })),
  reviewChoice: (choiceId: number, action: 'approve' | 'reject') =>
    unwrap<GaokaoChoiceReview>(http.patch(`/gaokao/choices/${choiceId}/review`, { action })),
  batchApproveChoices: (choiceIds: number[]) =>
    unwrap<{ updated: number; skipped: number }>(http.post('/gaokao/choices/batch-approve', { choice_ids: choiceIds })),
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

export interface StudentLoginResult {
  access_token: string
  token_type: string
  student: { id: number; name: string; student_no?: string | null; grade_id?: number | null; class_id?: number | null }
  school: { code: string; name: string; province: string }
}

export interface StudentChoiceOptions {
  scheme: {
    id: number
    name: string
    mode: '3+1+2' | '3+3' | 'traditional'
    required_subject_ids: number[]
    primary_subject_ids: number[]
    secondary_subject_ids: number[]
  } | null
  subjects: Array<{ id: number; name: string }>
  choice: {
    scheme_id: number
    primary_subject_id?: number | null
    secondary_subject_ids: number[]
    status: 'draft' | 'confirmed' | 'rejected' | 'locked'
  } | null
}

export const studentAuthApi = {
  login: (data: { login_name: string; password: string }) =>
    unwrap<StudentLoginResult>(http.post('/student-auth/login', data)),
  me: () => unwrap<StudentLoginResult['student']>(http.get('/student-auth/me')),
  context: () => unwrap<{ academic_year: string; term: string; student: StudentLoginResult['student'] }>(http.get('/student-auth/context')),
  options: (params: { academic_year: string; term: string }) =>
    unwrap<StudentChoiceOptions>(http.get('/student-auth/choice/options', { params })),
  choice: (params: { academic_year: string; term: string }) =>
    unwrap<unknown>(http.get('/student-auth/choice', { params })),
  saveChoice: (data: {
    scheme_id: number
    academic_year: string
    effective_term: string
    primary_subject_id?: number
    secondary_subject_ids: number[]
    status: 'draft' | 'confirmed'
  }) => unwrap<StudentChoiceOptions['choice']>(http.put('/student-auth/choice', data)),
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
  /** 按权限码预览角色侧栏菜单（可传草稿勾选） */
  roleMenuPreview: (roleId: number, codes?: string[]) =>
    unwrap<RoleMenuPreview>(
      http.get(`/rbac/roles/${roleId}/menu-preview`, {
        params: codes ? { codes: codes.join(',') } : undefined,
      }),
    ),
  /** 菜单可见权限映射列表 */
  menuPermissions: () =>
    unwrap<MenuPermissionBinding[]>(http.get('/rbac/menu-permissions')),
  /** 整量设置某菜单的可见权限点 */
  setMenuPermissions: (menuKey: string, permissions: string[]) =>
    unwrap<{ menu_key: string; permissions: string[] }>(
      http.put(`/rbac/menu-permissions/${menuKey}`, { permissions }),
    ),
}

export type FileTransferJobType = {
  value: string
  label: string
  direction: 'import' | 'export'
}

export type FileTransferJob = {
  id: string
  job_type: string
  job_type_label: string
  direction: 'import' | 'export'
  status: 'queued' | 'running' | 'success' | 'failed' | string
  progress: number
  processed: number
  total: number
  operator_id?: number | null
  operator_name?: string
  scope?: string
  file_name?: string | null
  object_key?: string | null
  file_size: number
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  downloadable?: boolean
}

/** 文件中心：异步导入 / 导出 / 下载 */
export const fileCenterApi = {
  jobTypes: () => unwrap<FileTransferJobType[]>(http.get('/file-center/job-types')),
  listJobs: (params?: { direction?: string; job_type?: string; status?: string; limit?: number }) =>
    unwrap<FileTransferJob[]>(http.get('/file-center/jobs', { params })),
  getJob: (jobId: string) => unwrap<FileTransferJob>(http.get(`/file-center/jobs/${jobId}`)),
  download: (jobId: string) =>
    unwrap<{ url: string; file_name?: string; file_size?: number }>(
      http.get(`/file-center/jobs/${jobId}/download`),
    ),
  exportTimetable: (data: {
    academic_year: string
    term: string
    class_ids?: number[] | null
    periods_per_day?: number
    evening_start_period?: number | null
    sheets?: string[]
  }) => unwrap<FileTransferJob>(http.post('/file-center/exports/timetable', data)),
  exportStudents: (data: {
    grade_id?: number | null
    class_id?: number | null
    unassigned_only?: boolean
  }) => unwrap<FileTransferJob>(http.post('/file-center/exports/students', data)),
  createImport: (data: { job_type: string; file: File; scope?: string }) => {
    const body = new FormData()
    body.append('job_type', data.job_type)
    if (data.scope) body.append('scope', data.scope)
    body.append('file', data.file)
    return unwrap<FileTransferJob>(http.post('/file-center/imports', body))
  },
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

export type AiProvider = {
  id: number
  name: string
  provider_type: string
  base_url: string
  has_api_key: boolean
  chat_model?: string | null
  vision_model?: string | null
  image_model?: string | null
  video_model?: string | null
  audio_model?: string | null
  timeout_seconds: number
  is_default: boolean
  status: number
  sort: number
  remark?: string | null
  last_test_status?: number | null
  last_test_at?: string | null
}

export type AiProviderForm = {
  name: string
  provider_type: string
  base_url: string
  api_key?: string
  chat_model?: string | null
  vision_model?: string | null
  image_model?: string | null
  video_model?: string | null
  audio_model?: string | null
  timeout_seconds?: number
  is_default?: boolean
  status?: number
  sort?: number
  remark?: string | null
}

export const aiProviderApi = {
  list: (params?: { keyword?: string; status?: number }) =>
    unwrap<AiProvider[]>(http.get('/ai-providers', { params })),
  create: (data: AiProviderForm) => unwrap<AiProvider>(http.post('/ai-providers', data)),
  update: (id: number, data: AiProviderForm) => unwrap<boolean>(http.put(`/ai-providers/${id}`, data)),
  updateStatus: (id: number, status: number) =>
    unwrap<boolean>(http.put(`/ai-providers/${id}/status`, null, { params: { status } })),
  setDefault: (id: number) => unwrap<boolean>(http.put(`/ai-providers/${id}/default`)),
  remove: (id: number) => unwrap<boolean>(http.delete(`/ai-providers/${id}`)),
  test: (id: number) => unwrap<boolean>(http.post(`/ai-providers/${id}/test`)),
  loadModels: (data: { provider_type?: string; base_url: string; api_key?: string }) =>
    unwrap<string[]>(http.post('/ai-providers/load-models', data)),
}

export type AssistantPlan = {
  id: string
  status: 'pending' | 'executed' | 'cancelled'
  summary: string
  expires_at: string
  result?: { text: string; path: string; count: number } | null
}

export type AssistantExecution = {
  mode: 'pending' | 'direct' | 'agent' | 'supervisor'
  multi_agent: boolean
  kind: 'readiness' | 'diagnosis' | null
  tasks: {
    id: string
    label: string
    status: 'running' | 'succeeded' | 'failed'
    attempt?: number
    retry_count?: number
    allowed_tools?: string[]
  }[]
}

export type AssistantRun = {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted'
  phase: string
  message: string
  elapsed_seconds: number
  phase_elapsed_seconds: number
  heartbeat_at: string
  events: { phase: string; message: string; at: string }[]
  execution?: AssistantExecution
  result?: { text: string; think?: string[]; choices?: { label: string; send: string }[]; plan?: AssistantPlan | null; jumps?: { label: string; path: string; requires_confirmation?: boolean }[]; model_visible?: boolean } | null
}

export type AssistantConversation = {
  messages: { role: 'user' | 'assistant'; content: string; model_visible?: boolean }[]
  summary: string
  updated_at?: string | null
}

export const assistantApi = {
  conversation: () => unwrap<AssistantConversation>(http.get('/assistant/conversation', { timeout: 5000 })),
  saveConversation: (messages: AssistantConversation['messages']) =>
    unwrap<AssistantConversation>(http.put('/assistant/conversation', { messages }, { timeout: 5000 })),
  clearConversation: () => unwrap<{ cleared: boolean }>(http.delete('/assistant/conversation', { timeout: 5000 })),
  startRun: (data: Record<string, unknown>, signal?: AbortSignal) =>
    unwrap<AssistantRun>(http.post('/assistant/runs', data, { timeout: 8000, signal })),
  readRun: (id: string, signal?: AbortSignal) =>
    unwrap<AssistantRun>(http.get(`/assistant/runs/${encodeURIComponent(id)}`, { timeout: 5000, signal })),
  steerRun: (id: string, content: string) =>
    unwrap<{ accepted: boolean; kind: 'steer'; message_id: string }>(
      http.post(`/assistant/runs/${encodeURIComponent(id)}/steer`, { content }, { timeout: 5000 }),
    ),
  cancelRun: (id: string) =>
    unwrap<AssistantRun>(http.post(`/assistant/runs/${encodeURIComponent(id)}/cancel`, {}, { timeout: 5000 })),
  decide: (id: string, decision: 'confirm' | 'cancel') =>
    unwrap<AssistantPlan>(http.post(`/assistant/actions/${encodeURIComponent(id)}`, { decision })),
}

export type KnowledgeBase = {
  id: number
  name: string
  description: string
  embedding_model: string
  enabled: boolean
  created_at?: string | null
}

export const knowledgeApi = {
  list: () => unwrap<KnowledgeBase[]>(http.get('/knowledge')),
  create: (data: Pick<KnowledgeBase, 'name' | 'description' | 'embedding_model'>) =>
    unwrap<KnowledgeBase>(http.post('/knowledge', data)),
  setStatus: (id: number, enabled: boolean) =>
    unwrap<KnowledgeBase>(http.patch(`/knowledge/${id}/status`, null, { params: { enabled } })),
  remove: (id: number) => unwrap<{ deleted: boolean }>(http.delete(`/knowledge/${id}`)),
}

export type OnboardingStep = {
  key: string
  title: string
  done: boolean
  detail: string
  path: string
}

export type OnboardingStatus = {
  steps: OnboardingStep[]
  done_count: number
  total: number
  history_year?: string | null
  dismissed: boolean
}

export const onboardingApi = {
  status: (signal?: AbortSignal) =>
    unwrap<OnboardingStatus>(http.get('/onboarding/status', { timeout: 8000, signal })),
  dismiss: () => unwrap<{ dismissed: boolean }>(http.post('/onboarding/dismiss', {}, { timeout: 8000 })),
  reopen: () => unwrap<{ dismissed: boolean }>(http.post('/onboarding/reopen', {}, { timeout: 8000 })),
}

export { setAuthResolver }
export type { AuthResolver } from './http'
