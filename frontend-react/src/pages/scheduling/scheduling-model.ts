import type {
  ScheduleRuleConfig,
  ScheduleRuleTemplate,
  SchedulingGridConfig,
} from '@/types'

export const NOW = new Date()
export const SCHOOL_YEAR = NOW.getMonth() >= 7 ? NOW.getFullYear() : NOW.getFullYear() - 1
export const MONDAY = (() => {
  const value = new Date(NOW)
  value.setDate(NOW.getDate() - ((NOW.getDay() + 6) % 7))
  return value
})()

export const SUBJECT_ORDER = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '体育']
export const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export const GEN_STEPS = [
  { code: 'validating', label: '校验资源' },
  { code: 'generating', label: '初排与冲突修复' },
  { code: 'refreshing', label: '保存并验算' },
  { code: 'done', label: '生成完成' },
] as const

export type GenStage = 'idle' | (typeof GEN_STEPS)[number]['code'] | 'blocked' | 'error'

export interface GenerationSuggestion {
  rule_id: string
  code: string
  title: string
  action: 'demote_to_soft' | 'disable' | 'relax_param' | 'check_hours' | string
  action_label?: string
  reason: string
  impact: string
  priority?: number
  applicable?: boolean
  param_patch?: Record<string, unknown> | null
}

export interface GenerationDiagnosis {
  summary?: string
  failure_kind?: string
  solver?: string | null
  rule_group_id?: string | null
  pipeline?: Array<{ id: string; label: string }>
  stuck_step?: string
  stuck_label?: string
  reasons?: string[]
  suggestions?: GenerationSuggestion[]
  hard_rules_in_effect?: Array<{
    rule_id: string
    code: string
    title: string
  }>
}

export interface GenTraceEvent {
  ts?: number
  stage?: string
  phase?: string
  message?: string
  percent?: number
  elapsed?: number
  solutions?: number
}

export interface GenerationAuditState {
  generating: boolean
  stage: GenStage
  percent: number
  elapsed: number
  solutions: number
  summary: string
  trace: GenTraceEvent[]
  diagnosis: GenerationDiagnosis | null
  groupId?: string
}

export const DEFAULT_GEN_PIPELINE = [
  { id: 'validating', label: '校验任教与课时' },
  { id: 'daytime_search', label: '白天课求解' },
  { id: 'evening_search', label: '晚自习求解' },
  { id: 'hard_rule_postcheck', label: '硬规则验算' },
  { id: 'refreshing', label: '写入课表' },
] as const

/** 折叠求解心跳，保留阶段切换与关键消息 */
export const appendGenTrace = (
  prev: GenTraceEvent[],
  event: GenTraceEvent,
): GenTraceEvent[] => {
  const next: GenTraceEvent = {
    ts: event.ts ?? Date.now() / 1000,
    stage: event.stage,
    phase: event.phase || event.stage,
    message: event.message,
    percent: event.percent,
    elapsed: event.elapsed,
    solutions: event.solutions,
  }
  const last = prev[prev.length - 1]
  const heartbeat = typeof next.message === 'string' && /已用时\s*\d+s/.test(next.message)
  if (
    last &&
    heartbeat &&
    last.phase === next.phase &&
    last.stage === next.stage
  ) {
    return [...prev.slice(0, -1), next].slice(-60)
  }
  return [...prev, next].slice(-60)
}

/** 从生成失败 detail / Error.message 中解析诊断信息 */
export const parseGenerationDiagnosis = (raw: unknown): GenerationDiagnosis | null => {
  const tryParse = (value: unknown): GenerationDiagnosis | null => {
    if (!value || typeof value !== 'object') return null
    const obj = value as Record<string, unknown>
    const nested =
      obj.diagnosis && typeof obj.diagnosis === 'object'
        ? (obj.diagnosis as Record<string, unknown>)
        : obj
    const reasons = Array.isArray(nested.reasons)
      ? nested.reasons.filter((item): item is string => typeof item === 'string')
      : []
    const suggestions = Array.isArray(nested.suggestions)
      ? (nested.suggestions as GenerationSuggestion[])
      : []
    if (!reasons.length && !suggestions.length && typeof nested.summary !== 'string') {
      return null
    }
    return {
      summary: typeof nested.summary === 'string' ? nested.summary : undefined,
      failure_kind:
        typeof nested.failure_kind === 'string' ? nested.failure_kind : undefined,
      solver: typeof nested.solver === 'string' ? nested.solver : null,
      rule_group_id:
        typeof nested.rule_group_id === 'string' ? nested.rule_group_id : null,
      pipeline: Array.isArray(nested.pipeline)
        ? (nested.pipeline as GenerationDiagnosis['pipeline'])
        : undefined,
      stuck_step: typeof nested.stuck_step === 'string' ? nested.stuck_step : undefined,
      stuck_label:
        typeof nested.stuck_label === 'string' ? nested.stuck_label : undefined,
      reasons,
      suggestions,
      hard_rules_in_effect: Array.isArray(nested.hard_rules_in_effect)
        ? (nested.hard_rules_in_effect as GenerationDiagnosis['hard_rules_in_effect'])
        : undefined,
    }
  }

  const direct = tryParse(raw)
  if (direct) return direct
  if (typeof raw === 'string') {
    try {
      return tryParse(JSON.parse(raw))
    } catch {
      return null
    }
  }
  if (raw instanceof Error) {
    try {
      return tryParse(JSON.parse(raw.message))
    } catch {
      return null
    }
  }
  return null
}

export interface AssignmentForm {
  mode?: 'subject' | 'activity'
  teacher_id?: number
  subject_id?: number
  class_id?: number
  weekly_periods: number
  room: string
}

export interface ScheduleAdjustmentCheck {
  key: string
  label: string
  passed: boolean
  severity?: string
}

export interface ScheduleAdjustmentOption {
  weekday: number
  period: number
  week_parity?: 'all' | 'odd' | 'even'
  available: boolean
  selectable?: boolean
  reason: string
  mode?: 'move' | 'swap'
  checks?: ScheduleAdjustmentCheck[]
  swap_schedule_id?: number | null
  swap_with_subject?: string | null
  swap_with_teacher?: string | null
}

export interface SubstituteOption {
  teacher_id: number
  teacher_name: string
  weekly_lessons: number
  available: boolean
  reason: string
}

export const DEFAULT_GRID_CONFIG: SchedulingGridConfig = {
  days: 5,
  periods_per_day: 7,
  enable_saturday: false,
  enable_evening: false,
  daily_periods: [7, 7, 7, 7, 7, 0, 0],
  evening_start_period: null,
  evening_daily_periods_odd: [0, 0, 0, 0, 0, 0, 0],
  evening_daily_periods_even: [0, 0, 0, 0, 0, 0, 0],
  evening_subject_ids: [],
  evening_subject_ids_odd: [],
  evening_subject_ids_even: [],
  term_start_monday: null,
  first_week_parity: 'odd',
}

export const DEFAULT_RULE_CONFIG: ScheduleRuleConfig = {
  days: 5,
  periods_per_day: 8,
  saturday_periods: 7,
  enable_evening: false,
  evening_start_period: null,
  evening_daily_periods_odd: [0, 0, 0, 0, 0, 0, 0],
  evening_daily_periods_even: [0, 0, 0, 0, 0, 0, 0],
  evening_subject_ids: [],
  evening_subject_ids_odd: [],
  evening_subject_ids_even: [],
  max_class_lessons_per_day: 8,
  max_teacher_lessons_per_day: 6,
  max_class_lessons_on_saturday: 7,
  max_teacher_lessons_on_saturday: 7,
  max_pe_teacher_lessons_per_day: 4,
  max_teacher_weekly_periods: 30,
  pe_weekly_periods: 2,
  max_same_subject_per_day: 2,
  require_full_week: false,
  avoid_consecutive_teacher_lessons: true,
  forbidden_slots: [],
  strategy_codes: ['cross_day_variety', 'class_compact', 'daily_balance', 'cross_class_gap_repair', 'random_tiebreak'],
}

export const BUILTIN_PERIOD_PLANS: Array<{ name: string; rules: Record<string, number> }> = [
  { name: '标准方案', rules: { 语文: 5, 数学: 5, 英语: 5, 物理: 3, 化学: 3, 生物: 2, 政治: 2, 历史: 2, 地理: 2, 体育: 1 } },
]

export const PERIOD_PLANS_KEY = 'scheduling.period_plans.v1'
export const DEFAULT_RULE_TEMPLATE_KEY = 'scheduling.default_rule_template_id'
export const RULE_TEMPLATES_KEY = 'scheduling.rule_templates.v1'
export const RULE_CONFIG_REVISION_KEY = 'scheduling.rule_config_revision'
export const RULE_CONFIG_REVISION = '2026-08-29-course-hours-v4'

export function localDateValue(value: Date): string {
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-')
}

export function cloneRuleConfig(config: ScheduleRuleConfig = DEFAULT_RULE_CONFIG): ScheduleRuleConfig {
  return JSON.parse(JSON.stringify(config)) as ScheduleRuleConfig
}

export function buildBuiltinRuleTemplates(now = new Date()): ScheduleRuleTemplate[] {
  const timestamp = now.toISOString()
  return [
    {
      id: 'builtin-balanced',
      name: '常规均衡排课',
      desc: '课时足额 / 同科分散 / 禁排时段',
      enabled: true,
      config: DEFAULT_RULE_CONFIG,
      created_at: timestamp,
      updated_at: timestamp,
    },
    {
      id: 'builtin-intensive',
      name: '集中紧凑排课',
      desc: '班级课表紧凑；同科课时仍由算法按全周自动分散',
      enabled: true,
      config: {
        ...DEFAULT_RULE_CONFIG,
        max_same_subject_per_day: 3,
        avoid_consecutive_teacher_lessons: false,
      },
      created_at: timestamp,
      updated_at: timestamp,
    },
  ]
}

function normalizeRuleTemplates(templates: ScheduleRuleTemplate[], applyRecommendedConfig: boolean): ScheduleRuleTemplate[] {
  return templates.map((template) => {
    const config = template.config || DEFAULT_RULE_CONFIG
    const legacyEveningSubjects = config.evening_subject_ids ?? []
    const oddSubjects = Array.isArray(config.evening_subject_ids_odd)
      ? config.evening_subject_ids_odd
      : legacyEveningSubjects
    const evenSubjects = Array.isArray(config.evening_subject_ids_even)
      ? config.evening_subject_ids_even
      : legacyEveningSubjects

    return {
      ...template,
      enabled: template.enabled !== false,
      config: {
        ...DEFAULT_RULE_CONFIG,
        ...(applyRecommendedConfig && template.id === 'builtin-balanced' ? {} : config),
        saturday_parity: 'all' as const,
        enable_evening: applyRecommendedConfig ? false : (config.enable_evening ?? false),
        evening_start_period: applyRecommendedConfig ? null : (config.evening_start_period ?? null),
        evening_daily_periods_odd: applyRecommendedConfig
          ? [0, 0, 0, 0, 0, 0, 0]
          : (config.evening_daily_periods_odd ?? [0, 0, 0, 0, 0, 0, 0]),
        evening_daily_periods_even: applyRecommendedConfig
          ? [0, 0, 0, 0, 0, 0, 0]
          : (config.evening_daily_periods_even ?? [0, 0, 0, 0, 0, 0, 0]),
        evening_subject_ids_odd: oddSubjects,
        evening_subject_ids_even: evenSubjects,
        evening_subject_ids: [...new Set([...oddSubjects, ...evenSubjects])],
      },
    }
  })
}

export function loadRuleTemplates(storage: Storage = localStorage): ScheduleRuleTemplate[] {
  try {
    const raw = storage.getItem(RULE_TEMPLATES_KEY)
    if (!raw) return buildBuiltinRuleTemplates()

    const parsed = JSON.parse(raw) as ScheduleRuleTemplate[]
    const templates = Array.isArray(parsed) && parsed.length ? parsed : buildBuiltinRuleTemplates()
    const applyRecommendedConfig = storage.getItem(RULE_CONFIG_REVISION_KEY) !== RULE_CONFIG_REVISION
    const normalized = normalizeRuleTemplates(templates, applyRecommendedConfig)

    if (applyRecommendedConfig) {
      storage.setItem(RULE_CONFIG_REVISION_KEY, RULE_CONFIG_REVISION)
      storage.setItem(RULE_TEMPLATES_KEY, JSON.stringify(normalized))
    }
    return normalized
  } catch {
    return buildBuiltinRuleTemplates()
  }
}

export function keepSingleEnabledTemplate(
  templates: ScheduleRuleTemplate[],
  preferredId: string,
): ScheduleRuleTemplate[] {
  const enabled = templates.filter((template) => template.enabled !== false)
  if (enabled.length <= 1) return templates

  const keep = enabled.find((template) => template.id === preferredId) || enabled[0]
  return templates.map((template) => ({ ...template, enabled: template.id === keep.id }))
}

/** 晚自习起始节次：随正式课每天上限推导，不写死第 9 节。 */
export function resolveEveningStartPeriod(
  grid: Pick<SchedulingGridConfig, 'daily_periods' | 'periods_per_day' | 'enable_evening' | 'evening_daily_periods_odd' | 'evening_daily_periods_even'>,
): number | null {
  const daily = Array.from({ length: 7 }, (_, index) => grid.daily_periods?.[index] ?? 0)
  const formalMax = Math.max(...daily, grid.periods_per_day || 0, 0)
  const odd = grid.evening_daily_periods_odd ?? []
  const even = grid.evening_daily_periods_even ?? []
  const enabled = Boolean(grid.enable_evening) || odd.some(Boolean) || even.some(Boolean)
  if (!enabled || formalMax <= 0) return null
  return formalMax + 1
}

/** 保存/下发前规范化：纠正过期的 evening_start_period。 */
export function normalizeGridConfig(grid: SchedulingGridConfig): SchedulingGridConfig {
  const daily_periods = Array.from({ length: 7 }, (_, index) => Math.max(0, Math.min(12, grid.daily_periods?.[index] ?? 0)))
  const periods_per_day = Math.max(...daily_periods, 1)
  const activeDays = daily_periods.reduce((last, value, index) => (value > 0 ? index + 1 : last), 0)
  const evening_daily_periods_odd = Array.from({ length: 7 }, (_, i) => grid.evening_daily_periods_odd?.[i] ?? 0)
  const evening_daily_periods_even = Array.from({ length: 7 }, (_, i) => grid.evening_daily_periods_even?.[i] ?? 0)
  const enable_evening = Boolean(grid.enable_evening)
    || evening_daily_periods_odd.some(Boolean)
    || evening_daily_periods_even.some(Boolean)
  return {
    ...grid,
    daily_periods,
    days: Math.max(5, activeDays),
    periods_per_day,
    enable_saturday: daily_periods[5] > 0,
    enable_evening,
    evening_start_period: enable_evening ? periods_per_day + 1 : null,
    evening_daily_periods_odd,
    evening_daily_periods_even,
  }
}

export function getConfiguredSlotOptions(gridConfig: SchedulingGridConfig): string[] {
  const dailyPeriods = Array.from({ length: 7 }, (_, index) => gridConfig.daily_periods[index] ?? 0)
  const oddEvening = Array.from({ length: 7 }, (_, index) => gridConfig.evening_daily_periods_odd[index] ?? 0)
  const evenEvening = Array.from({ length: 7 }, (_, index) => gridConfig.evening_daily_periods_even[index] ?? 0)
  const normalized = normalizeGridConfig(gridConfig)

  return WEEKDAY_NAMES.flatMap((day, index) => {
    const formalCount = dailyPeriods[index]
    const eveningCount = normalized.enable_evening ? Math.max(oddEvening[index], evenEvening[index]) : 0
    return Array.from({ length: formalCount + eveningCount }, (_, periodIndex) => `${day} · 第${periodIndex + 1}节`)
  })
}

export function buildRuleGridConfig(
  config: ScheduleRuleConfig,
  gridConfig: SchedulingGridConfig,
): SchedulingGridConfig {
  const dailyPeriods = Array.from({ length: 7 }, (_, index) => gridConfig.daily_periods[index] ?? 0)
  const activeDays = dailyPeriods.reduce((lastDay, periods, index) => periods > 0 ? index + 1 : lastDay, 0)
  const formalPeriods = Math.max(...dailyPeriods, 0)
  const eveningDailyPeriodsOdd = gridConfig.evening_daily_periods_odd ?? [0, 0, 0, 0, 0, 0, 0]
  const eveningDailyPeriodsEven = gridConfig.evening_daily_periods_even ?? [0, 0, 0, 0, 0, 0, 0]
  const eveningEnabled = Boolean(gridConfig.enable_evening)
  const legacyEveningSubjects = gridConfig.evening_subject_ids ?? []
  const oddSubjects = config.evening_subject_ids_odd ?? legacyEveningSubjects
  const evenSubjects = config.evening_subject_ids_even ?? legacyEveningSubjects

  return normalizeGridConfig({
    ...gridConfig,
    days: activeDays,
    periods_per_day: formalPeriods,
    daily_periods: dailyPeriods,
    enable_saturday: dailyPeriods[5] > 0,
    enable_evening: eveningEnabled,
    evening_daily_periods_odd: eveningDailyPeriodsOdd,
    evening_daily_periods_even: eveningDailyPeriodsEven,
    evening_subject_ids: [...new Set([...oddSubjects, ...evenSubjects])],
    evening_subject_ids_odd: oddSubjects,
    evening_subject_ids_even: evenSubjects,
  })
}

export function buildGenerationPayload(
  config: ScheduleRuleConfig,
  gridConfig: SchedulingGridConfig,
  academicYear: string,
  term: string,
) {
  const ruleGrid = buildRuleGridConfig(config, gridConfig)
  const strategyCodes = [
    'daily_balance',
    ...config.strategy_codes.filter((code) => code !== 'daily_balance'),
  ]
  const structuralForbidden: Array<[number, number]> = []

  ruleGrid.daily_periods.slice(0, ruleGrid.days).forEach((available, dayIndex) => {
    for (let period = available + 1; period <= ruleGrid.periods_per_day; period += 1) {
      structuralForbidden.push([dayIndex + 1, period])
    }
  })

  const forbidden = new Map<string, [number, number]>()
  ;[
    ...config.forbidden_slots.map((slot) => slot.split('-').map(Number) as [number, number]),
    ...structuralForbidden,
  ].forEach((slot) => forbidden.set(`${slot[0]}-${slot[1]}`, slot))

  return {
    academic_year: academicYear,
    term,
    days: ruleGrid.days,
    periods_per_day: ruleGrid.periods_per_day,
    // 负荷上限与硬约束必须随生成请求下发，否则后端按“无限制”排课。
    max_class_lessons_per_day: config.max_class_lessons_per_day,
    max_teacher_lessons_per_day: config.max_teacher_lessons_per_day,
    max_class_lessons_on_saturday: config.max_class_lessons_on_saturday,
    max_teacher_lessons_on_saturday: config.max_teacher_lessons_on_saturday,
    max_pe_teacher_lessons_per_day: config.max_pe_teacher_lessons_per_day,
    max_teacher_weekly_periods: config.max_teacher_weekly_periods,
    max_same_subject_per_day: config.max_same_subject_per_day,
    require_full_week: config.require_full_week,
    avoid_consecutive_teacher_lessons: config.avoid_consecutive_teacher_lessons,
    enable_evening: ruleGrid.enable_evening,
    evening_start_period: ruleGrid.evening_start_period,
    evening_daily_periods_odd: ruleGrid.evening_daily_periods_odd,
    evening_daily_periods_even: ruleGrid.evening_daily_periods_even,
    evening_subject_ids: ruleGrid.evening_subject_ids,
    evening_subject_ids_odd: ruleGrid.evening_subject_ids_odd,
    evening_subject_ids_even: ruleGrid.evening_subject_ids_even,
    forbidden_slots: [...forbidden.values()],
    strategy_codes: strategyCodes,
  }
}
