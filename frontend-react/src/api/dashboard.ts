/** dashboard 领域 API（由 api/index.ts 拆分）。 */
import type {
  Exam,
} from '@/types'
import { http, unwrap } from './http'

export interface DashboardSummary {
  exams: Array<
    Exam & { ongoing: boolean }
  >
  ongoing_count: number
}

export const dashboardApi = {
  summary: () => unwrap<DashboardSummary>(http.get('/dashboard/summary')),
}

/** 角色与权限（RBAC） */
