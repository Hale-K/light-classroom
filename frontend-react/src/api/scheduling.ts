/** scheduling 领域 API（由 api/index.ts 拆分）。 */
import type {
  ScheduleEntry,
  ScheduleStrategyOption,
  ScheduleValidationResult,
  ScheduleVersionSummary,
  SchedulingResources,
  SchedulingRuleGroup,
  SchedulingRuleGroupCatalog,
  SchedulingRuleValidationResult,
} from '@/types'
import { ApiError, http, unwrap } from './http'

export const schedulingApi = {
  resources: (params?: { academic_year?: string; term?: string }) => unwrap<SchedulingResources>(http.get('/scheduling/resources', { params })),
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
  inheritTermData: (data: { academic_year: string; from_term: string; to_term: string; class_ids?: number[]; copy_course_hours: boolean; copy_assignments: boolean; copy_rules: boolean }) =>
    unwrap<{
      academic_year: string
      from_term: string
      to_term: string
      course_hours_created: number
      course_hours_replaced: number
      assignments_created: number
      assignments_updated: number
      rule_groups_created_or_copied: number
      rule_groups_replaced: number
    }>(http.post('/scheduling/inherit-term-data', data)),
  gridConfig: (params: { academic_year: string; term: string; grade_id?: number }) =>
    unwrap<import('@/types').SchedulingGridConfig>(http.get('/scheduling/grid-config', { params })),
  saveGridConfig: (data: import('@/types').SchedulingGridConfig & { academic_year: string; term: string; grade_id?: number }) =>
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

