/** teacherProfiles 领域 API（由 api/index.ts 拆分）。 */
import { http, unwrap } from './http'

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

