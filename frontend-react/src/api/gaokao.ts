/** gaokao 领域 API（由 api/index.ts 拆分）。 */
import type {
  Grade,
  ScheduleEntry,
} from '@/types'
import { http, unwrap } from './http'

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
  teaching_classes?: Array<{ subject_id: number; weekly_periods: number }>
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

export interface WalkTeachingClass {
  id: number
  name: string
  subject_id: number
  subject_name: string
  sequence: number
  capacity: number
  weekly_periods: number
  weekday_periods: number | null
  weekend_periods: number | null
  hours_overridden?: boolean
  teacher_id: number | null
  room: string | null
  student_count: number
  teacher_name?: string | null
  students: Array<{
    id: number
    student_no: string | null
    name: string
    administrative_class: string | null
  }>
}

export const gaokaoApi = {
  studentTimetable: (studentId: number, params: { academic_year: string; term: string }) =>
    unwrap<ScheduleEntry[]>(http.get(`/gaokao/student-timetable/${studentId}`, { params })),
  recommendWalkConfiguration: (data: { grade_id: number; academic_year: string; term: string; room_ids?: number[]; forbidden_slots?: [number, number][] }) =>
    unwrap<{ status: string; message: string; lower_bound?: number; recommended_count?: number; slots?: [number, number][]; room_ids?: number[];
      student_count?: number; roster_student_count: number; student_hours_min?: number; student_hours_max?: number; total_class_periods?: number;
      room_count?: number; peak_concurrent_classes?: number; minimal_proven?: boolean; warnings: string[]; bounds?: {rooms: number; students: number; teachers: number};
      rule_failures?: Array<{ rule_id: string; title: string; message: string }>;
      rule_results?: Array<{ rule_id: string; code: string; title: string; priority: string; status: string; message: string }>;
      daily_slot_counts?: number[]; combined_hours_min?: number; combined_hours_max?: number;
      placements?: Array<{ teaching_class_id: number; class_name: string; teacher_id: number; weekday: number; period: number; room_id: number; room_name: string }> }>(http.post('/gaokao/walk-configuration/recommend', data, { timeout: 25000 })),
  teachingClassTeachers: (params: { academic_year: string; term: string }) =>
    unwrap<Array<{ id: number; name: string; subject_ids: number[]; administrative_periods: number; walk_periods: number; total_periods: number }>>(http.get('/gaokao/teaching-classes/teachers', { params })),
  assignTeachingClassTeachers: (data: { grade_id: number; academic_year: string; term: string; assignments: Array<{ teaching_class_id: number; teacher_id: number | null; expected_teacher_id: number | null }> }) =>
    unwrap<{ updated: number }>(http.patch('/gaokao/teaching-classes/teachers', data)),
  myStudents: (includeTeaching = false) => unwrap<import('@/types').Student[]>(http.get('/gaokao/my-students', {
    params: includeTeaching ? { include_teaching: true } : undefined,
  })),
  overview: (params: { academic_year: string; term: string; grade_id?: number }) =>
    unwrap<GaokaoOverview>(http.get('/gaokao/overview', { params })),
  choicesForReview: (params: { academic_year: string; term: string; grade_id?: number; status_filter?: string }) =>
    unwrap<GaokaoChoiceReview[]>(http.get('/gaokao/choices', { params })),
  reviewChoice: (choiceId: number, action: 'approve' | 'reject' | 'reopen') =>
    unwrap<GaokaoChoiceReview>(http.patch(`/gaokao/choices/${choiceId}/review`, { action })),
  batchApproveChoices: (choiceIds: number[]) =>
    unwrap<{ updated: number; skipped: number }>(http.post('/gaokao/choices/batch-approve', { choice_ids: choiceIds })),
  generateTeachingClasses: (data: {
    grade_id: number
    academic_year: string
    term: string
    capacity?: number
    weekly_periods?: number
    weekly_periods_by_subject?: Record<number, number>
    primary_delivery_mode?: 'administrative' | 'teaching_class'
    preview?: boolean
    replace_existing?: boolean
    preview_token?: string
  }) =>
    unwrap<{ created: number; memberships: number; existing_class_count?: number; available_room_count?: number;
      preview_token?: string; warnings?: string[];
      classes?: Array<{ subject_id: number; subject_name: string; sequence: number; student_count: number; weekly_periods: number }> }>(
      http.post('/gaokao/teaching-classes/generate', data),
    ),
  previewRegroupPlan: (data: { grade_id: number; academic_year: string; term: string; capacity: number; capacity_overflow: number; weekdays: number[]; periods: number[] }) =>
    unwrap<{ preview_token: string; student_count: number; class_count: number;
      audit: Record<string, number>; replaced_rule_ids: string[];
      classes: Array<{ id: number; name: string; subject_name: string; student_count: number; capacity: number }>;
      admin_classes: Array<{ id: number; name: string }>;
      students: Array<{ id: number; name: string; class_id: number; class_name: string; teaching_class_ids: number[];
        primary_subject_name: string; secondary_subject_names: string[] }>;
      slots: Array<{ weekday: number; period: number }>;
      lessons: Array<{ kind: 'admin' | 'walk'; class_id: number; class_name: string; subject_name: string;
        teacher_id: number; teacher_name: string; room: string; weekday: number; period: number }> }>(
      http.post('/gaokao/teaching-classes/regroup-plan', data, { timeout: 180000 }),
    ),
  saveRegroupPlan: (data: { grade_id: number; academic_year: string; term: string; preview_token: string; confirm_replace: true }) =>
    unwrap<{ saved: boolean; class_count: number; student_count: number; public_lessons: number; walk_lessons: number; audit: Record<string, number> }>(
      http.post('/gaokao/teaching-classes/regroup-save', data, { timeout: 60000 }),
    ),
  updateTeachingSubjectHours: (data: {
    grade_id: number
    academic_year: string
    term: string
    subject_id: number
    weekly_periods?: number
    weekday_periods?: number
    weekend_periods?: number
  }) => unwrap<{ updated: number; weekly_periods: number; cleared_schedule_count: number }>(
    http.patch('/gaokao/teaching-classes/subject-hours', data),
  ),
  teachingSubjectHours: (params: { grade_id: number; academic_year: string; term: string }) =>
    unwrap<Record<string, number>>(http.get('/gaokao/teaching-classes/subject-hours', { params })),
  teachingSubjectHourDetails: (params: { grade_id: number; academic_year: string; term: string }) =>
    unwrap<Record<string, { weekly_periods: number; weekday_periods: number | null; weekend_periods: number | null }>>(
      http.get('/gaokao/teaching-classes/subject-hours', { params: { ...params, detailed: true } })),
  updateTeachingClassHours: (classId: number, data: { grade_id: number; academic_year: string; term: string; weekly_periods?: number; weekday_periods?: number; weekend_periods?: number }) =>
    unwrap<{ updated: number; cleared_schedule_count: number }>(http.patch(`/gaokao/teaching-classes/${classId}/hours`, data)),
  teachingClasses: (params: { grade_id: number; academic_year: string; term: string }) =>
    unwrap<WalkTeachingClass[]>(http.get('/gaokao/teaching-classes', { params })),
  teachingClassRoster: (classId: number, params: { academic_year: string; term: string }) =>
    unwrap<{
      teaching_class_id: number
      teaching_class_name: string
      subject_id: number
      total: number
      items: Array<{ student_id: number; student_no: string | null; student_name: string; class_name: string | null }>
    }>(http.get(`/gaokao/teaching-classes/${classId}/roster`, { params })),
  walkClassSpacePool: (params: { grade_id: number; academic_year: string; term?: string }) =>
      unwrap<{ grade_id: number; academic_year: string; term: string | null; physics_room_ids: number[]; history_room_ids: number[]; shared_room_ids: number[]; available_rooms: Array<{ id: number; name: string; capacity: number }> }>(
        http.get('/gaokao/space-pool', { params }),
      ),
  saveWalkClassSpacePool: (data: {
    grade_id: number
    academic_year: string
    term?: string
    physics_room_ids: number[]
    history_room_ids: number[]
    shared_room_ids: number[]
  }) =>
    unwrap<{ grade_id: number; academic_year: string; physics_room_ids: number[]; history_room_ids: number[]; shared_room_ids: number[] }>(
      http.put('/gaokao/space-pool', data),
    ),
  schedules: (params: { academic_year: string; term: string; grade_id?: number; student_id?: number }) =>
    unwrap<Array<{
      id: number
      teaching_class_id: number
      teaching_class_name: string
      teacher_id: number | null
      teacher_name: string
      subject_id: number
      subject_name: string
      academic_year: string
      term: string
      weekday: number
      period: number
      room: string | null
    }>>(http.get('/gaokao/schedules', { params })),
  clearSchedules: (data: { grade_id: number; academic_year: string; term: string }) =>
    unwrap<{ cleared: number; teaching_class_count: number }>(http.post('/gaokao/schedules/clear', data)),
  generateSchedule: (data: {
    grade_id: number
    academic_year: string
    term: string
    days?: number
    periods_per_day?: number
    room_ids?: number[]
  }) =>
    unwrap<{ created: number; teaching_class_count: number; unplaced: Array<{ teaching_class_id: number; count: number }>;
      room_count: number; room_ids: number[]; slots: [number, number][]; daily_slot_counts: number[]; peak_concurrent_classes?: number;
      placements: Array<{ teaching_class_id: number; class_name: string; teacher_id: number; weekday: number; period: number; room_id: number; room_name: string }>;
      rule_results: Array<{ rule_id: string; code: string; title: string; priority: string; status: string; message: string }>;
      warnings: string[] }>(
      http.post('/gaokao/schedules/generate', data),
    ),
}

