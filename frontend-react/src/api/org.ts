/** org 领域 API（由 api/index.ts 拆分）。 */
import type {
  AutoClassAssignmentResult,
  ClassInfo,
  Grade,
  OrganizationTreeResult,
  OrganizationUnit,
  StaffAccount,
  StaffAppointment,
  StaffDirectory,
  StaffRoleCode,
  Student,
} from '@/types'
import { http, unwrap } from './http'

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
  classes: (params?: { grade_id?: number; academic_year?: string; term?: string }) =>
    unwrap<ClassInfo[]>(http.get('/org/classes', { params })),
  assignHeadTeacher: (classId: number, data: { teacher_id: number; academic_year: string; term: string }) =>
    unwrap<ClassInfo>(http.patch(`/org/classes/${classId}/head-teacher`, data)),
  createClass: (data: { grade_id: number; name: string; home_room_id?: number; class_type?: string; planned_student_count?: number; head_teacher_id?: number }) =>
    unwrap<ClassInfo>(http.post('/org/classes', data)),
  updateClassResourcePlan: (id: number, data: { home_room_id: number | null; class_type: string }) =>
    unwrap<ClassInfo>(http.patch(`/org/classes/${id}/resource-plan`, data)),
  autoAssignPreview: (data: { grade_id: number; class_ids: number[]; strategy: string; balance_gender?: boolean; overwrite_existing?: boolean }) =>
    unwrap<AutoClassAssignmentResult>(http.post('/org/classes/auto-assign/preview', data)),
  autoAssign: (data: { grade_id: number; class_ids: number[]; strategy: string; balance_gender?: boolean; overwrite_existing?: boolean }) =>
    unwrap<AutoClassAssignmentResult>(http.post('/org/classes/auto-assign', data)),
  students: (class_id?: number, campus_id?: number, grade_id?: number, scope?: { academic_year?: string; term?: string; cohort_label?: string }) =>
    unwrap<Student[]>(http.get('/org/students', { params: { class_id, campus_id, grade_id, ...scope } })),
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
  assignStudents: (student_ids: number[], class_id: number | null, scope?: { academic_year?: string; term?: string; grade_id?: number; cohort_label?: string }) =>
    unwrap<{ updated: number; class_id: number | null }>(
      http.patch('/org/students/assign-class', { student_ids, class_id, ...scope }),
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

