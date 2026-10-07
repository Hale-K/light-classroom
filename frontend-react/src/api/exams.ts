/** exams 领域 API（由 api/index.ts 拆分）。 */
import type {
  Exam,
  ExamCandidateAssignment,
  ExamInvigilatorEntry,
  ExamPlan,
  ExamRoomEntry,
  ExamScheduleEntry,
  ExamVenuePlan,
  ExamSchedulingConfig,
} from '@/types'
import { http, unwrap } from './http'

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
  create: (data: { name: string; exam_type: string; academic_year: string; term: string }) =>
    unwrap<Exam>(http.post('/exams', data)),
  updateStatus: (id: number, status: string) =>
    unwrap<Exam>(http.patch(`/exams/${id}/status`, { status })),
}

