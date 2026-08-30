import { useEffect, useMemo, useState } from 'react'
import { App, Button, DatePicker, Dropdown, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tabs, Tag } from 'antd'
import type { TableProps, MenuProps } from 'antd'
import dayjs from 'dayjs'
import type { Dayjs } from 'dayjs'
import { authApi, orgApi, schedulingApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import TableCard from '@/components/TableCard'
import ScheduleGrid from '@/components/ScheduleGrid'
import Icon from '@/components/Icon'
import type {
  Grade,
  ScheduleEntry,
  ScheduleRuleConfig,
  ScheduleRuleTemplate,
  ScheduleStrategyOption,
  SchedulingGridConfig,
  SchedulingResources,
  ScheduleValidationIssue,
  ScheduleValidationResult,
  ScheduleVersionSummary,
  TeacherScopeRule,
  TeachingAssignment,
} from '@/types'
import RuleDesigner from './RuleDesigner'
import CourseHoursPanel from './course-hours'
import './index.css'

/** 初始时间基线：学年 / 学期 / 本周一（与 Vue 版一致） */
const NOW = new Date()
const SCHOOL_YEAR = NOW.getMonth() >= 7 ? NOW.getFullYear() : NOW.getFullYear() - 1
const MONDAY = (() => {
  const d = new Date(NOW)
  d.setDate(NOW.getDate() - ((NOW.getDay() + 6) % 7))
  return d
})()
const localDateValue = (value: Date) => [
  value.getFullYear(),
  String(value.getMonth() + 1).padStart(2, '0'),
  String(value.getDate()).padStart(2, '0'),
].join('-')
const SUBJECT_ORDER = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '体育']
const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const GEN_STEPS = [
  { code: 'validating', label: '校验资源' },
  { code: 'generating', label: '初排与冲突修复' },
  { code: 'refreshing', label: '保存并刷新' },
  { code: 'done', label: '生成完成' },
] as const
type GenStage = 'idle' | (typeof GEN_STEPS)[number]['code'] | 'blocked' | 'error'

interface AssignmentForm {
  mode?: 'subject' | 'activity'
  teacher_id?: number
  subject_id?: number
  class_id?: number
  weekly_periods: number
  room: string
}

interface ScheduleAdjustmentOption {
  weekday: number
  period: number
  available: boolean
  reason: string
}

interface SubstituteOption {
  teacher_id: number
  teacher_name: string
  weekly_lessons: number
  available: boolean
  reason: string
}

export default function SchedulingView() {
  const { message } = App.useApp()

  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genStage, setGenStage] = useState<GenStage>('idle')
  const [failedStageIndex, setFailedStageIndex] = useState(0)
  const [issues, setIssues] = useState<ScheduleValidationIssue[]>([])
  const [showAllIssues, setShowAllIssues] = useState(false)
  const [validation, setValidation] = useState<ScheduleValidationResult | null>(null)
  const [validatedSignature, setValidatedSignature] = useState('')
  const [validatingRules, setValidatingRules] = useState(false)
  const [genSummary, setGenSummary] = useState('')

  const [scheduleVersions, setScheduleVersions] = useState<ScheduleVersionSummary[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)

  const [activeTab, setActiveTab] = useState<'hours' | 'rules' | 'assignments' | 'schedule'>('hours')
  const [resources, setResources] = useState<SchedulingResources>({
    teachers: [],
    subjects: [],
    classes: [],
    assignments: [],
    teaching_track_subject_ids: [],
  })
  const [strategies, setStrategies] = useState<ScheduleStrategyOption[]>([])
  const [calendar, setCalendar] = useState<ScheduleEntry[]>([])
  const [selectedClassId, setSelectedClassId] = useState<number>()
  const [assignKeyword, setAssignKeyword] = useState('')
  const [appliedAssignKeyword, setAppliedAssignKeyword] = useState('')
  const [assignPage, setAssignPage] = useState(1)
  const [assignPageSize, setAssignPageSize] = useState(10)
  const [academicYear, setAcademicYear] = useState(`${SCHOOL_YEAR}-${SCHOOL_YEAR + 1}`)
  const [term, setTerm] = useState(NOW.getMonth() >= 1 && NOW.getMonth() < 7 ? '2' : '1')
  const [weekStart, setWeekStart] = useState<string>(localDateValue(MONDAY))
  const [gridConfigVisible, setGridConfigVisible] = useState(false)
  const [gridConfig, setGridConfig] = useState<SchedulingGridConfig>({
    days: 5, periods_per_day: 7, enable_saturday: false, enable_evening: false,
    daily_periods: [7, 7, 7, 7, 7, 0, 0], evening_start_period: null,
    evening_daily_periods_odd: [0, 0, 0, 0, 0, 0, 0],
    evening_daily_periods_even: [0, 0, 0, 0, 0, 0, 0],
    evening_subject_ids: [], evening_subject_ids_odd: [], evening_subject_ids_even: [],
    term_start_monday: null, first_week_parity: 'odd',
  })

  // 弹窗
  const [assignmentVisible, setAssignmentVisible] = useState(false)
  const [editingAssignment, setEditingAssignment] = useState<TeachingAssignment>()
  const [assignmentModalTitle, setAssignmentModalTitle] = useState('新建任教关系')
  const [teacherVisible, setTeacherVisible] = useState(false)
  const [conditionVisible, setConditionVisible] = useState(false)
  const [generationRuleVisible, setGenerationRuleVisible] = useState(false)
  const [adjustmentEntry, setAdjustmentEntry] = useState<ScheduleEntry>()
  const [adjustmentOptions, setAdjustmentOptions] = useState<ScheduleAdjustmentOption[]>([])
  const [adjustmentLoading, setAdjustmentLoading] = useState(false)
  const [movingSchedule, setMovingSchedule] = useState(false)
  const [substituteOptions, setSubstituteOptions] = useState<SubstituteOption[]>([])
  const [adjustmentTab, setAdjustmentTab] = useState<'move' | 'substitute'>('move')
  const [scopeRuleVisible, setScopeRuleVisible] = useState(false)
  const [scopeRules, setScopeRules] = useState<TeacherScopeRule[]>([])
  const [scopeRuleForm, setScopeRuleForm] = useState<Partial<TeacherScopeRule>>({ mode: 'allow', weekly_periods: 4 })
  const [scopeRuleFilter, setScopeRuleFilter] = useState<Partial<TeacherScopeRule>>({})
  const [scopeRuleFormVisible, setScopeRuleFormVisible] = useState(false)
  const [editingScopeRuleKey, setEditingScopeRuleKey] = useState<string | undefined>()
  const autoWeeklyPeriods = 4
  const [grades, setGrades] = useState<Grade[]>([])
  const [autoGradeIds, setAutoGradeIds] = useState<number[]>([])
  // 课时方案：内置标准方案 + 本地自定义方案，一键填充学科课时规则
  const PERIOD_PLANS_KEY = 'scheduling.period_plans.v1'
  const BUILTIN_PERIOD_PLANS: Array<{ name: string; rules: Record<string, number> }> = [
    { name: '标准方案', rules: { 语文: 5, 数学: 5, 英语: 5, 物理: 3, 化学: 3, 生物: 2, 政治: 2, 历史: 2, 地理: 2, 体育: 1 } },
  ]
  const [periodPlans, setPeriodPlans] = useState<Array<{ name: string; rules: Record<string, number> }>>([])
  const allPeriodPlans = useMemo(() => [...BUILTIN_PERIOD_PLANS, ...periodPlans], [periodPlans])
  // 自动生成：按课时方案直接生成任教关系
  const [templateGenVisible, setTemplateGenVisible] = useState(false)
  const [templateGenPlan, setTemplateGenPlan] = useState('标准方案')
  const [templateGenLoading, setTemplateGenLoading] = useState(false)
  const [templateGenIssues, setTemplateGenIssues] = useState<string[]>([])
  const [assignmentForm, setAssignmentForm] = useState<AssignmentForm>({
    weekly_periods: 4,
    room: '',
  })
  const [teacherForm, setTeacherForm] = useState({ name: '', phone: '', password: '123456' })
  const [conditions, setConditions] = useState<ScheduleRuleConfig>({
      days: 5,
      periods_per_day: 6,
      max_class_lessons_per_day: 6,
      max_teacher_lessons_per_day: 6,
      max_teacher_weekly_periods: 30,
      max_same_subject_per_day: 2,
    require_full_week: true,
    avoid_consecutive_teacher_lessons: true,
    forbidden_slots: [] as string[],
    strategy_codes: ['cross_day_variety', 'class_compact', 'daily_balance', 'cross_class_gap_repair', 'random_tiebreak'],
  })
  // 教师每周课时上限：负荷上限（规则设计器）配置，供智能编排与规则表格默认值使用
  const autoMaxWeeklyPeriods = conditions.max_teacher_weekly_periods ?? 30
  // 不同届存在同名班级时，下拉选项追加届标签区分（如 高一（1）班（2029届））
  const duplicateClassNames = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of resources.classes) counts.set(item.name, (counts.get(item.name) || 0) + 1)
    return new Set([...counts.entries()].filter(([, count]) => count > 1).map(([name]) => name))
  }, [resources.classes])
  const classOption = (item: { id: number; name: string; cohort_label?: string | null }) => ({
    label: duplicateClassNames.has(item.name) && item.cohort_label ? `${item.name}（${item.cohort_label}届）` : item.name,
    value: item.id,
  })
  const [savingAssignment, setSavingAssignment] = useState(false)
  const [savingTeacher, setSavingTeacher] = useState(false)

  // ---------- 规则模板（建立规则 Tab） ----------
  const DEFAULT_RULE_TEMPLATE_KEY = 'scheduling.default_rule_template_id'
  const RULE_TEMPLATES_KEY = 'scheduling.rule_templates.v1'
  const RULE_CONFIG_REVISION_KEY = 'scheduling.rule_config_revision'
  const RULE_CONFIG_REVISION = '2026-08-29-course-hours-v4'
  const DEFAULT_RULE_CONFIG: ScheduleRuleConfig = {
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
  const buildInTemplates = (): ScheduleRuleTemplate[] => [
    {
      id: 'builtin-balanced',
      name: '常规均衡排课',
      desc: '课时足额 / 同科分散 / 禁排时段',
      enabled: true,
      config: DEFAULT_RULE_CONFIG,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
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
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]
  const loadTemplates = (): ScheduleRuleTemplate[] => {
    try {
      const raw = localStorage.getItem(RULE_TEMPLATES_KEY)
      if (!raw) return buildInTemplates()
      const parsed = JSON.parse(raw) as ScheduleRuleTemplate[]
      const list = Array.isArray(parsed) && parsed.length ? parsed : buildInTemplates()
      const applyRecommendedConfig = localStorage.getItem(RULE_CONFIG_REVISION_KEY) !== RULE_CONFIG_REVISION
      // 兼容旧数据：无 enabled 字段视为启用
      const normalized = list.map((t) => ({
        ...t,
        enabled: t.enabled !== false,
        config: {
          ...DEFAULT_RULE_CONFIG,
          ...(applyRecommendedConfig && t.id === 'builtin-balanced' ? {} : t.config),
          saturday_parity: 'all' as const,
          enable_evening: applyRecommendedConfig ? false : (t.config.enable_evening ?? false),
          evening_start_period: applyRecommendedConfig ? null : (t.config.evening_start_period ?? null),
          evening_daily_periods_odd: applyRecommendedConfig ? [0, 0, 0, 0, 0, 0, 0] : (t.config.evening_daily_periods_odd ?? [0, 0, 0, 0, 0, 0, 0]),
          evening_daily_periods_even: applyRecommendedConfig ? [0, 0, 0, 0, 0, 0, 0] : (t.config.evening_daily_periods_even ?? [0, 0, 0, 0, 0, 0, 0]),
          evening_subject_ids_odd: Array.isArray(t.config.evening_subject_ids_odd) ? t.config.evening_subject_ids_odd : (t.config.evening_subject_ids ?? []),
          evening_subject_ids_even: Array.isArray(t.config.evening_subject_ids_even) ? t.config.evening_subject_ids_even : (t.config.evening_subject_ids ?? []),
          evening_subject_ids: [...new Set([
            ...(Array.isArray(t.config.evening_subject_ids_odd) ? t.config.evening_subject_ids_odd : (t.config.evening_subject_ids ?? [])),
            ...(Array.isArray(t.config.evening_subject_ids_even) ? t.config.evening_subject_ids_even : (t.config.evening_subject_ids ?? [])),
          ])],
        },
      }))
      if (applyRecommendedConfig) {
        localStorage.setItem(RULE_CONFIG_REVISION_KEY, RULE_CONFIG_REVISION)
        localStorage.setItem(RULE_TEMPLATES_KEY, JSON.stringify(normalized))
      }
      return normalized
    } catch {
      return buildInTemplates()
    }
  }
  const [ruleTemplates, setRuleTemplates] = useState<ScheduleRuleTemplate[]>(() => {
    const loaded = loadTemplates()
    // 互斥归一化：最多只保留一个开启；默认模板优先，否则第一个
    const defaultId = localStorage.getItem(DEFAULT_RULE_TEMPLATE_KEY) || 'builtin-balanced'
    const enabledCount = loaded.filter(t => t.enabled !== false).length
    if (enabledCount <= 1) return loaded
    const keep = loaded.find(t => t.id === defaultId && t.enabled !== false) || loaded.find(t => t.enabled !== false)
    return loaded.map(t => t.id === keep?.id
      ? { ...t, enabled: true }
      : { ...t, enabled: false })
  })
  const [defaultRuleTemplateId, setDefaultRuleTemplateId] = useState<string>(
    () => localStorage.getItem(DEFAULT_RULE_TEMPLATE_KEY) || 'builtin-balanced',
  )
  const [ruleTemplateModalOpen, setRuleTemplateModalOpen] = useState(false)
  const [editingRuleTemplateId, setEditingRuleTemplateId] = useState<string>()
  const [ruleTemplateForm, setRuleTemplateForm] = useState<{
    name: string
    desc: string
    config: ScheduleRuleConfig
    scope_rules: TeacherScopeRule[]
  }>({
    name: '',
    desc: '',
    config: DEFAULT_RULE_CONFIG,
    scope_rules: [],
  })
  const persistRuleTemplates = (next: ScheduleRuleTemplate[]) => {
    setRuleTemplates(next)
    try { localStorage.setItem(RULE_TEMPLATES_KEY, JSON.stringify(next)) } catch {}
  }
  useEffect(() => {
    // 初次挂载时若无默认，选第一个启用的模板（互斥模式下唯一开启者）
    if (!ruleTemplates.some(t => t.id === defaultRuleTemplateId)) {
      const firstEnabled = ruleTemplates.find(t => t.enabled !== false)
      if (firstEnabled) setDefaultRuleTemplateId(firstEnabled.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    try { localStorage.setItem(DEFAULT_RULE_TEMPLATE_KEY, defaultRuleTemplateId) } catch {}
  }, [defaultRuleTemplateId])
  const openRuleTemplateModal = (record?: ScheduleRuleTemplate) => {
    if (record) {
      setEditingRuleTemplateId(record.id)
      setRuleTemplateForm({
        name: record.name,
        desc: record.desc || '',
        config: JSON.parse(JSON.stringify(record.config)),
        scope_rules: JSON.parse(JSON.stringify(record.scope_rules || [])),
      })
    } else {
      setEditingRuleTemplateId(undefined)
      setRuleTemplateForm({
        name: '',
        desc: '',
        config: JSON.parse(JSON.stringify(DEFAULT_RULE_CONFIG)),
        scope_rules: [],
      })
    }
    setRuleTemplateModalOpen(true)
  }
  const saveRuleTemplate = () => {
    const name = ruleTemplateForm.name.trim()
    if (!name) {
      message.warning('请填写规则模板名称')
      return
    }
    const scopePayload = ruleTemplateForm.scope_rules.length > 0
      ? JSON.parse(JSON.stringify(ruleTemplateForm.scope_rules))
      : undefined
    if (editingRuleTemplateId) {
      persistRuleTemplates(ruleTemplates.map(t => t.id === editingRuleTemplateId
        ? { ...t, name, desc: ruleTemplateForm.desc, config: ruleTemplateForm.config, scope_rules: scopePayload, updated_at: new Date().toISOString() }
        : t))
      message.success('规则模板已更新')
    } else {
      const newTpl: ScheduleRuleTemplate = {
        id: `tpl_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        name,
        desc: ruleTemplateForm.desc,
        config: ruleTemplateForm.config,
        scope_rules: scopePayload,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      persistRuleTemplates([...ruleTemplates, newTpl])
      message.success('规则模板已创建')
    }
    setRuleTemplateModalOpen(false)
  }
  const deleteRuleTemplate = (record: ScheduleRuleTemplate) => {
    if (record.id.startsWith('builtin-')) {
      message.warning('内置规则模板不可删除')
      return
    }
    const next = ruleTemplates.filter(t => t.id !== record.id)
    persistRuleTemplates(next)
    if (defaultRuleTemplateId === record.id) {
      setDefaultRuleTemplateId(next[0]?.id || '')
    }
    message.success('规则模板已删除')
  }
  const toggleRuleTemplate = (record: ScheduleRuleTemplate) => {
    const turningOn = record.enabled === false
    let next: ScheduleRuleTemplate[]
    if (turningOn) {
      // 开启一个 → 其余全部停用（最多只允许一个开启）
      next = ruleTemplates.map(t => t.id === record.id
        ? { ...t, enabled: true, updated_at: new Date().toISOString() }
        : { ...t, enabled: false })
      setDefaultRuleTemplateId(record.id)
      void applyRuleTemplateAsConditions(record)
    } else {
      // 关闭当前开启的 → 全部停用，无生效模板
      next = ruleTemplates.map(t => t.id === record.id
        ? { ...t, enabled: false, updated_at: new Date().toISOString() }
        : t)
      if (defaultRuleTemplateId === record.id) {
        setDefaultRuleTemplateId('')
      }
    }
    persistRuleTemplates(next)
    message.success(turningOn ? `规则「${record.name}」已启用` : `规则「${record.name}」已停用`)
  }
  // 当前 Tab 生效使用的规则：唯一开启的模板（最多只允许一个开启）
  const activeRuleTemplate = useMemo(
    () => ruleTemplates.find(t => t.enabled !== false) || undefined,
    [ruleTemplates],
  )
  const applyRuleTemplateAsConditions = async (record: ScheduleRuleTemplate) => {
    setConditions(JSON.parse(JSON.stringify(record.config)))
    setValidation(null)
    setValidatedSignature('')
    // —— 同步模板的教师任教范围到全局（后端 TenantConfig 持久化 + 前端 scopeRules 状态）——
    //    这样 autoTeaching（自动生成任教关系）和 generate 仍然通过读后端生效，无需改接口
    const scopeRulesClone: TeacherScopeRule[] = JSON.parse(JSON.stringify(record.scope_rules || []))
    setScopeRules(scopeRulesClone)
    try {
      await schedulingApi.saveScopeRules({ academic_year: academicYear, term, rules: scopeRulesClone })
    } catch (e) {
      // 静默失败，避免影响模板切换
    }
  }

  const selectedClassName = useMemo(
    () => resources.classes.find((item) => item.id === selectedClassId)?.name || '全部班级',
    [resources.classes, selectedClassId],
  )
  const visibleAssignments = useMemo(
    () =>
      resources.assignments.filter(
        (item) =>
          item.academic_year === academicYear &&
          item.term === term &&
          (selectedClassId === undefined || item.class_id === selectedClassId),
      ).sort((a, b) => {
        const classDiff = (a.class_name || '').localeCompare(b.class_name || '', 'zh-CN', { numeric: true })
        if (classDiff !== 0) return classDiff
        const subjectDiff = SUBJECT_ORDER.indexOf(a.subject_name || '') - SUBJECT_ORDER.indexOf(b.subject_name || '')
        if (subjectDiff !== 0) return subjectDiff
        return (a.teacher_name || '').localeCompare(b.teacher_name || '', 'zh-CN')
      }),
    [resources.assignments, academicYear, term, selectedClassId],
  )
  const filteredAssignments = useMemo(() => {
    const query = appliedAssignKeyword.trim().toLowerCase()
    return visibleAssignments.filter((item) => {
      if (!query) return true
      return (
        (item.subject_name || '').toLowerCase().includes(query) ||
        (item.teacher_name || '').toLowerCase().includes(query) ||
        (item.class_name || '').toLowerCase().includes(query) ||
        (item.room || '').toLowerCase().includes(query)
      )
    })
  }, [visibleAssignments, appliedAssignKeyword])
  const pagedAssignments = useMemo(
    () => filteredAssignments.slice((assignPage - 1) * assignPageSize, assignPage * assignPageSize),
    [filteredAssignments, assignPage, assignPageSize],
  )
  const handleSearchAssignment = () => {
    setAppliedAssignKeyword(assignKeyword)
    setAssignPage(1)
  }
  const resetAssignmentFilters = () => {
    setAssignKeyword('')
    setAppliedAssignKeyword('')
    setAssignPage(1)
  }

  const genStepIndex = useMemo(() => {
    const index = GEN_STEPS.findIndex((item) => item.code === genStage)
    return index >= 0 ? index : failedStageIndex
  }, [genStage, failedStageIndex])

  const ruleGridConfig = (config: ScheduleRuleConfig): SchedulingGridConfig => {
    // 时段结构由“周格设置”唯一维护，规则模板只提供排课约束与策略。
    const dailyPeriods = Array.from({ length: 7 }, (_, index) => gridConfig.daily_periods[index] ?? 0)
    const activeDays = dailyPeriods.reduce((lastDay, periods, index) => periods > 0 ? index + 1 : lastDay, 0)
    const formalPeriods = Math.max(...dailyPeriods, 0)
    // 晚自习的起始节次和每日容量也由“周格设置”维护，不跟随排课规则模板切换。
    const eveningDailyPeriodsOdd = gridConfig.evening_daily_periods_odd ?? [0, 0, 0, 0, 0, 0, 0]
    const eveningDailyPeriodsEven = gridConfig.evening_daily_periods_even ?? [0, 0, 0, 0, 0, 0, 0]
    const eveningEnabled = Boolean(gridConfig.enable_evening)
    const legacyEveningSubjects = gridConfig.evening_subject_ids ?? []
    return {
      ...gridConfig,
      days: activeDays,
      periods_per_day: formalPeriods,
      daily_periods: dailyPeriods,
      enable_saturday: dailyPeriods[5] > 0,
      enable_evening: eveningEnabled,
      // 晚自习是独立时段，始终自动接在当天正式课之后，不再由用户填写第几节。
      evening_start_period: eveningEnabled ? formalPeriods + 1 : null,
      evening_daily_periods_odd: eveningDailyPeriodsOdd,
      evening_daily_periods_even: eveningDailyPeriodsEven,
      evening_subject_ids: [...new Set([
        ...(config.evening_subject_ids_odd ?? legacyEveningSubjects),
        ...(config.evening_subject_ids_even ?? legacyEveningSubjects),
      ])],
      evening_subject_ids_odd: config.evening_subject_ids_odd ?? legacyEveningSubjects,
      evening_subject_ids_even: config.evening_subject_ids_even ?? legacyEveningSubjects,
    }
  }

  const generationPayload = (config: ScheduleRuleConfig = conditions) => {
    const ruleGrid = ruleGridConfig(config)
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

  const payloadSignature = () => JSON.stringify(generationPayload())
  const validationIsCurrent = Boolean(validation?.valid && validatedSignature === payloadSignature())

  const issueText = (issue: ScheduleValidationIssue) => {
    if (issue.code === 'primary_admin_track_conflict') {
      const className =
        resources.classes.find((item) => item.id === issue.entity_id)?.name ||
        `班级 ${issue.entity_id}`
      return `${className}同时配置了物理和历史；请按首选科目重分行政班，或将首选科目切换为教学班走班`
    }
    if (issue.entity_type === 'teacher') {
      const name =
        resources.teachers.find((item) => item.id === issue.entity_id)?.name ||
        `教师 ${issue.entity_id}`
      return `${name}承担 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
    }
    const className =
      resources.classes.find((item) => item.id === issue.entity_id)?.name ||
      `班级 ${issue.entity_id}`
    if (issue.entity_type === 'class_subject') {
      const subjectName =
        resources.subjects.find((item) => item.id === issue.related_id)?.name || '该学科'
      return `${className}的${subjectName}需要 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
    }
    return `${className}需要 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
  }

  const loadResources = async () => {
    const [data, strategyOptions, academicSettings] = await Promise.all([
      schedulingApi.resources(),
      schedulingApi.strategies(),
      authApi.academicYears(),
    ])
    setResources(data)
    setStrategies(strategyOptions)
    if (academicSettings.current_academic_year) setAcademicYear(academicSettings.current_academic_year)
    if (academicSettings.current_term) setTerm(academicSettings.current_term)
    setSelectedClassId((prev) => prev ?? data.classes[0]?.id)
  }

  const loadScopeRules = async () => {
    try {
      setScopeRules(await schedulingApi.scopeRules({ academic_year: academicYear, term }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '教师搭班规则加载失败')
    }
  }

  /** 自动生成任教关系可用的年级范围（弹窗打开时加载） */
  const loadAutoGrades = async () => {
    try {
      setGrades(await orgApi.grades())
    } catch {
      setGrades([])
    }
  }

  const openScopeRuleModal = async () => {
    setScopeRuleFilter({})
    await loadScopeRules()
    setScopeRuleVisible(true)
  }

  const openNewScopeRuleForm = () => {
    setEditingScopeRuleKey(undefined)
    setScopeRuleForm({ mode: 'allow', weekly_periods: 4 })
    setScopeRuleFormVisible(true)
  }

  const openEditScopeRuleForm = (record: TeacherScopeRule) => {
    setEditingScopeRuleKey(`${record.teacher_id}-${record.class_id}`)
    setScopeRuleForm({
      teacher_id: record.teacher_id,
      class_id: record.class_id,
      mode: record.mode,
      weekly_periods: record.weekly_periods ?? 4,
      subject_id: record.subject_id ?? undefined,
    })
    setScopeRuleFormVisible(true)
  }

  const closeScopeRuleForm = () => {
    setScopeRuleFormVisible(false)
    setEditingScopeRuleKey(undefined)
  }

  const submitScopeRuleForm = async () => {
    if (!scopeRuleForm.teacher_id || !scopeRuleForm.class_id || !scopeRuleForm.mode) {
      message.warning('请选择教师、班级和规则类型')
      return
    }
    const teacherId = scopeRuleForm.teacher_id
    const classId = scopeRuleForm.class_id
    const mode = scopeRuleForm.mode
    const teacher = resources.teachers.find((item) => item.id === teacherId)
    const classItem = resources.classes.find((item) => item.id === classId)
    const nextRule: TeacherScopeRule = {
      teacher_id: teacherId,
      teacher_name: teacher?.name,
      class_id: classId,
      class_name: classItem?.name,
      subject_id: scopeRuleForm.subject_id ?? null,
      mode: mode as 'allow' | 'deny',
      weekly_periods: scopeRuleForm.weekly_periods || null,
      fixed_weekday: scopeRuleForm.fixed_weekday ?? null,
      fixed_period: scopeRuleForm.fixed_period ?? null,
    }
    const key = editingScopeRuleKey ?? `${teacherId}-${classId}`
    let nextRules: TeacherScopeRule[]
    if (editingScopeRuleKey && editingScopeRuleKey !== key) {
      nextRules = [
        ...scopeRules.filter((item) => `${item.teacher_id}-${item.class_id}` !== editingScopeRuleKey && !(item.teacher_id === teacherId && item.class_id === classId)),
        nextRule,
      ]
    } else {
      nextRules = [
        ...scopeRules.filter((item) => !(item.teacher_id === teacherId && item.class_id === classId)),
        nextRule,
      ]
    }
    setScopeRules(nextRules)
    try {
      await schedulingApi.saveScopeRules({ academic_year: academicYear, term, rules: nextRules })
      message.success(editingScopeRuleKey ? '规则已更新' : '规则已添加')
      closeScopeRuleForm()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '规则保存失败')
    }
  }

  const resetScopeRuleQuery = () => {
    setScopeRuleForm({ mode: 'allow', weekly_periods: 4 })
    setScopeRuleFilter({})
  }

  const queryScopeRules = () => {
    setScopeRuleFilter({
      teacher_id: scopeRuleForm.teacher_id,
      class_id: scopeRuleForm.class_id,
      mode: scopeRuleForm.mode,
    })
  }

  const visibleScopeRules = useMemo(() => scopeRules.filter((rule) => (
    (scopeRuleFilter.teacher_id === undefined || rule.teacher_id === scopeRuleFilter.teacher_id) &&
    (scopeRuleFilter.class_id === undefined || rule.class_id === scopeRuleFilter.class_id) &&
    (scopeRuleFilter.mode === undefined || rule.mode === scopeRuleFilter.mode)
  )), [scopeRules, scopeRuleFilter])

  const periodPlanEntries = (plan: { name: string; rules: Record<string, number> }) => Object.entries(plan.rules)
    .map(([subjectName, weeklyPeriods]) => {
      const subject = resources.subjects.find((item) => item.name === subjectName && !resources.teaching_track_subject_ids?.includes(item.id))
      return subject ? { subject_id: subject.id, weekly_periods: weeklyPeriods } : null
    })
    .filter((item): item is { subject_id: number; weekly_periods: number } => item !== null)

  const runTemplateGenerate = async () => {
    const plan = allPeriodPlans.find((item) => item.name === templateGenPlan)
    if (!plan) return
    const entries = periodPlanEntries(plan)
    if (!entries.length) {
      message.warning('方案中没有可用学科')
      return
    }
    setTemplateGenLoading(true)
    setTemplateGenIssues([])
    try {
      const currentGrid = ruleGridConfig(conditions)
      const classIds = autoGradeIds.length > 0
        ? resources.classes.filter((item) => autoGradeIds.includes(item.grade_id)).map((item) => item.id)
        : undefined
      const payload = {
        academic_year: academicYear,
        term,
        class_ids: classIds,
        weekly_periods: autoWeeklyPeriods,
        max_weekly_periods: autoMaxWeeklyPeriods,
        subject_period_rules: entries,
        subject_teacher_limits: entries.map((item) => ({ subject_id: item.subject_id, max_weekly_periods: autoMaxWeeklyPeriods })),
        days: currentGrid.days,
        periods_per_day: currentGrid.periods_per_day,
        forbidden_slots: conditions.forbidden_slots.map((slot) => slot.split('-').map(Number) as [number, number]),
        max_class_lessons_per_day: conditions.max_class_lessons_per_day,
        max_teacher_lessons_per_day: conditions.max_teacher_lessons_per_day,
        max_same_subject_per_day: conditions.max_same_subject_per_day,
      }
      const preview = await schedulingApi.autoTeaching({ ...payload, execute: false })
      if (preview.skipped_count > 0 || preview.workload_summary.some((item) => !item.sufficient)) {
        const reasons = (preview.plan || [])
          .filter((row) => row.status === 'skipped')
          .slice(0, 10)
          .map((row) => `${row.class_name || row.class_id} · ${row.subject_name || row.subject_id}：${row.reason}`)
        setTemplateGenIssues(reasons.length ? reasons : ['存在教师负荷不足的学科，请调整方案或教师每周上限'])
        return
      }
      await schedulingApi.autoTeaching({ ...payload, execute: true })
      message.success(`已按「${plan.name}」生成 ${preview.created_count} 条任教关系`)
      setTemplateGenVisible(false)
      await loadResources()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '自动生成失败')
    } finally {
      setTemplateGenLoading(false)
    }
  }

  const loadTable = async () => {
    if (!selectedClassId) return
    if (!generating) setLoading(true)
    try {
      const c = await schedulingApi.weekly({
        class_id: selectedClassId,
        academic_year: academicYear,
        term,
      })
      setCalendar(c)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '课表加载失败')
    } finally {
      if (!generating) setLoading(false)
    }
  }

  const openAdjustment = async (entry: ScheduleEntry, event: React.MouseEvent<HTMLDivElement>) => {
    event.preventDefault()
    setAdjustmentEntry(entry)
    setAdjustmentOptions([])
    setSubstituteOptions([])
    setAdjustmentTab('move')
    setAdjustmentLoading(true)
    try {
      const rule = ruleGridConfig(activeRuleTemplate?.config || conditions)
      const [options, substitutes] = await Promise.all([
        schedulingApi.adjustmentOptions({
          schedule_id: entry.id,
          academic_year: academicYear,
          term,
          days: rule.days,
          periods_per_day: rule.periods_per_day,
        }),
        schedulingApi.substitutes({ schedule_id: entry.id, academic_year: academicYear, term }),
      ])
      setAdjustmentOptions(options)
      setSubstituteOptions(substitutes)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '可调课时加载失败')
      setAdjustmentEntry(undefined)
    } finally {
      setAdjustmentLoading(false)
    }
  }

  const applySubstitute = async (option: SubstituteOption) => {
    if (!adjustmentEntry || !option.available) return
    setMovingSchedule(true)
    try {
      await schedulingApi.substituteSchedule({
        schedule_id: adjustmentEntry.id,
        teacher_id: option.teacher_id,
        academic_year: academicYear,
        term,
      })
      setAdjustmentEntry(undefined)
      await loadTable()
      message.success(`已由 ${option.teacher_name} 代课`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '代课失败')
    } finally {
      setMovingSchedule(false)
    }
  }

  const moveEntry = async (option: ScheduleAdjustmentOption) => {
    if (!adjustmentEntry || !option.available) return
    setMovingSchedule(true)
    try {
      const rule = ruleGridConfig(activeRuleTemplate?.config || conditions)
      await schedulingApi.moveSchedule({
        schedule_id: adjustmentEntry.id,
        target_weekday: option.weekday,
        target_period: option.period,
        academic_year: academicYear,
        term,
        days: rule.days,
        periods_per_day: rule.periods_per_day,
      })
      setAdjustmentEntry(undefined)
      await loadTable()
      message.success('调课成功')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '调课失败')
    } finally {
      setMovingSchedule(false)
    }
  }

  const saveGridConfig = async () => {
    try {
      const saved = await schedulingApi.saveGridConfig({ ...gridConfig, academic_year: academicYear, term })
      setGridConfig(saved)
      setGridConfigVisible(false)
      message.success('排课周格已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '排课周格保存失败')
    }
  }

  useEffect(() => {
    void loadResources()
  }, [])

  useEffect(() => {
    try {
      const raw = localStorage.getItem(PERIOD_PLANS_KEY)
      const parsed = raw ? JSON.parse(raw) : []
      if (Array.isArray(parsed)) {
        setPeriodPlans(parsed.filter((item: { name?: unknown; rules?: unknown }) => (
          item && typeof item.name === 'string' && item.rules && typeof item.rules === 'object'
        )) as Array<{ name: string; rules: Record<string, number> }>)
      }
    } catch {
      // 方案数据损坏时忽略，使用内置方案
    }
  }, [])

  useEffect(() => {
    if (selectedClassId !== undefined) void loadTable()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClassId, academicYear, term, weekStart])

  useEffect(() => {
    void schedulingApi.gridConfig({ academic_year: academicYear, term })
      .then(setGridConfig)
      .catch(() => undefined)
  }, [academicYear, term])

  useEffect(() => {
    if (activeTab === 'schedule') void loadVersions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const updateConditions = (next: ScheduleRuleConfig) => {
    setConditions(next)
    setGridConfig(ruleGridConfig(next))
    setValidation(null)
    setValidatedSignature('')
    setIssues([])
  }

  const validateRules = async () => {
    if (!conditions.strategy_codes.length) {
      message.warning('请至少选择一种排课策略')
      return
    }
    setValidatingRules(true)
    setIssues([])
    try {
      const signature = payloadSignature()
      const savedGrid = await schedulingApi.saveGridConfig({
        ...ruleGridConfig(conditions),
        academic_year: academicYear,
        term,
      })
      setGridConfig(savedGrid)
      const result = await schedulingApi.validate(generationPayload())
      setValidation(result)
      setValidatedSignature(signature)
      setIssues(result.issues)
      if (result.valid) {
        setGenStage('idle')
        setConditionVisible(false)
        message.success('规则校验通过，可以生成课表')
      } else {
        setGenStage('blocked')
        setFailedStageIndex(0)
        setGenSummary(`发现 ${result.issues.length} 项硬冲突，请查看下方冲突提示`)
        message.warning('规则存在硬冲突')
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : ''
      if (detail.includes('请先配置当前学年学期的任教关系')) {
        // 规则编辑即时生效；容量校验依赖任教数据，未生成前任教时给出引导而非报错
        setConditionVisible(false)
        message.info('规则已保存并生效。生成任教关系后可再回来运行完整容量校验')
        return
      }
      message.error(detail || '规则校验失败')
    } finally {
      setValidatingRules(false)
    }
  }

  const generateAll = async () => {
    const generationConfig = activeRuleTemplate?.config || conditions
    setGenerating(true)
    setGenStage('generating')
    setFailedStageIndex(1)
    setIssues([])
    setGenSummary('正在生成课表')
    try {
      const payload = generationPayload(generationConfig)
      const result = await schedulingApi.generate(payload)
      setGenStage('refreshing')
      setFailedStageIndex(2)
      setGenSummary(`已生成 ${result.created} 节课，正在刷新周课表与日期课表`)
      await loadTable()
      setGenStage('done')
      setFailedStageIndex(3)
      setGenSummary(`已完成 ${result.class_count} 个班、${result.created} 节课`)
      const unplaced = result.unplaced?.reduce((sum, item) => sum + item.count, 0) ?? 0
      if (unplaced) message.warning(`已生成 ${result.created} 节，另有 ${unplaced} 节未能排入`)
      else message.success(`已为 ${result.class_count} 个班生成 ${result.created} 节课程`)
      void loadVersions()
    } catch (e) {
      setGenStage('error')
      setGenSummary(e instanceof Error ? e.message : '生成课表失败')
      message.error(e instanceof Error ? e.message : '生成课表失败')
    } finally {
      setGenerating(false)
    }
  }

  const openGenerationRulePreview = () => {
    const config = activeRuleTemplate?.config || conditions
    setConditions(JSON.parse(JSON.stringify(config)))
    setGenerationRuleVisible(true)
  }

  const loadVersions = async () => {
    try {
      setVersionsLoading(true)
      const list = await schedulingApi.listVersions()
      setScheduleVersions(list || [])
    } catch (e) {
      // 静默失败：版本列表不是核心功能
      setScheduleVersions([])
    } finally {
      setVersionsLoading(false)
    }
  }

  const restoreScheduleVersion = async (version: ScheduleVersionSummary) => {
    try {
      const result = await schedulingApi.restoreVersion(version.version_id)
      await loadTable()
      void loadVersions()
      message.success(`已恢复「${version.label}」，共 ${result.restored} 节`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '恢复历史版本失败')
    }
  }


  const saveAssignment = async () => {
    const isActivity = assignmentForm.mode === 'activity'
    if (!assignmentForm.class_id) {
      message.warning('请选择班级')
      return
    }
    if (isActivity && !assignmentForm.subject_id) {
      message.warning('请选择活动类型')
      return
    }
    if (!isActivity && !assignmentForm.teacher_id) {
      message.warning('请选择教师')
      return
    }
    if (!isActivity && !assignmentForm.subject_id) {
      message.warning('当前教师无法自动确定学科，请先在人员管理中关联唯一学科组')
      return
    }
    setSavingAssignment(true)
    try {
      await schedulingApi.saveAssignment({
        teacher_id: isActivity ? undefined : assignmentForm.teacher_id,
        subject_id: assignmentForm.subject_id,
        class_id: assignmentForm.class_id,
        academic_year: academicYear,
        term,
        weekly_periods: assignmentForm.weekly_periods,
        room: assignmentForm.room || undefined,
      })
      setAssignmentVisible(false)
      setValidation(null)
      setValidatedSignature('')
      await loadResources()
      message.success(editingAssignment ? '任教关系已更新' : '任教关系已保存')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSavingAssignment(false)
    }
  }

  const saveTeacher = async () => {
    if (!teacherForm.name || !teacherForm.phone || !teacherForm.password) {
      message.warning('请填写完整教师信息')
      return
    }
    setSavingTeacher(true)
    try {
      await schedulingApi.createTeacher(teacherForm)
      setTeacherVisible(false)
      setTeacherForm({ name: '', phone: '', password: '123456' })
      await loadResources()
      message.success('教师账号已创建')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSavingTeacher(false)
    }
  }

  const openAssignmentModal = () => {
    setEditingAssignment(undefined)
    setAssignmentModalTitle('新建任教关系')
    setAssignmentForm({ mode: 'subject', weekly_periods: 4, room: '' })
    setAssignmentVisible(true)
  }

  const editAssignment = (item: TeachingAssignment) => {
    setEditingAssignment(item)
    setAssignmentModalTitle(`编辑任教关系 · ${item.subject_name || ''}`)
    setAssignmentForm({
      mode: resources.subjects.find((subject) => subject.id === item.subject_id)?.course_type === 'activity' ? 'activity' : 'subject',
      teacher_id: item.teacher_id ?? undefined,
      subject_id: item.subject_id,
      class_id: item.class_id,
      weekly_periods: item.weekly_periods,
      room: item.room || '',
    })
    setAssignmentVisible(true)
  }

  const deleteAssignment = async (record: TeachingAssignment) => {
    try {
      await schedulingApi.deleteAssignment(record.id)
      setResources((prev) => ({
        ...prev,
        assignments: prev.assignments.filter((item) => item.id !== record.id),
      }))
      message.success('已删除任教关系')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '删除失败')
    }
  }

  const assignmentTeacherSubjectIds = assignmentForm.teacher_id
    ? resources.teacher_subject_ids?.[String(assignmentForm.teacher_id)] ?? []
    : []
  const assignmentSubjectName = assignmentForm.subject_id
    ? resources.subjects.find((item) => item.id === assignmentForm.subject_id)?.name
    : undefined
  const assignmentIsActivity = assignmentForm.mode === 'activity'
  const activitySubjects = resources.subjects.filter((subject) => subject.course_type === 'activity')

  const assignmentColumns: TableProps<TeachingAssignment>['columns'] = [
    { title: '班级', dataIndex: 'class_name', key: 'class_name', width: 200, ellipsis: true },
    { title: '学科', dataIndex: 'subject_name', key: 'subject_name', width: 90, ellipsis: true },
    { title: '教师', dataIndex: 'teacher_name', key: 'teacher_name', width: 230, ellipsis: true, render: (value?: string) => value || '活动安排' },
    {
      title: '课时方案',
      key: 'weekly_periods',
      width: 150,
      align: 'center',
      render: () => <Tag color="blue">课时管理维护</Tag>,
    },
    { title: '教室', dataIndex: 'room', key: 'room', width: 190, ellipsis: true, render: (v?: string) => v || '—' },
    {
      title: '操作',
      key: 'action',
      width: 130,
      align: 'right',
      render: (_: unknown, record: TeachingAssignment) => (
        <Space size={2}>
          <Button type="link" size="small" onClick={() => editAssignment(record)}>
            编辑
          </Button>
          <Popconfirm
            title="删除任教关系"
            description={`删除后该班「${record.subject_name}」的任教安排将不再保留，是否继续？`}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => void deleteAssignment(record)}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const genStateCopy = (() => {
    if (genStage === 'blocked') return '条件需要调整'
    if (genStage === 'error') return '生成未完成'
    if (genStage === 'done') return '课表生成完成'
    return '正在生成课表'
  })()

  return (
    <div className="sk-page">
      <PageHeader
        title="排课管理"
        extra={
          activeTab === 'rules' ? (
            <Button
              type="primary"
              size="large"
              icon={<Icon name="plus" size={14} />}
              onClick={() => openRuleTemplateModal()}
            >
              新建规则
            </Button>
          ) : activeTab === 'assignments' ? (
            <Button
              type="primary"
              size="large"
              icon={<Icon name="plus" size={14} />}
              onClick={openAssignmentModal}
            >
              新增任教关系
            </Button>
          ) : undefined
        }
      />
      <p className="zh-page-desc">先配置班级课时，再确定任教关系和排课规则，最后生成日课表；每一步都可以独立调整。</p>

      {genStage !== 'idle' && (
        <section
          className={`sk-status${genStage === 'blocked' || genStage === 'error' ? ' sk-status-fail' : ''}`}
          role="status"
          aria-live="polite"
        >
          <div className="sk-status-copy">
            <div>
              <strong>{genStateCopy}</strong>
              <span>{genSummary}</span>
            </div>
            {!generating && (
              <Button type="link" size="small" onClick={() => setGenStage('idle')}>
                收起
              </Button>
            )}
          </div>
          <div className="sk-track">
            {GEN_STEPS.map((step, index) => (
              <div
                key={step.code}
                className={[
                  'sk-step',
                  generating && genStepIndex === index ? 'active' : '',
                  genStepIndex > index || genStage === 'done' ? 'done' : '',
                  (genStage === 'blocked' || genStage === 'error') && genStepIndex === index
                    ? 'failed'
                    : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
              >
                <i aria-hidden="true" />
                <span>{step.label}</span>
              </div>
            ))}
          </div>
          {issues.length > 0 && (
            <ul className="sk-issues">
              {(showAllIssues ? issues : issues.slice(0, 8)).map((issue) => (
                <li key={`${issue.code}-${issue.entity_id}-${issue.related_id || 0}`}>
                  {issueText(issue)}
                </li>
              ))}
              {!showAllIssues && issues.length > 8 && (
                <li className="sk-issues-more">
                  另有 {issues.length - 8} 项冲突，
                  <Button type="link" size="small" onClick={() => setShowAllIssues(true)}>
                    展开全部
                  </Button>
                </li>
              )}
              {showAllIssues && issues.length > 8 && (
                <li className="sk-issues-more">
                  <Button type="link" size="small" onClick={() => setShowAllIssues(false)}>
                    收起
                  </Button>
                </li>
              )}
            </ul>
          )}
        </section>
      )}

      <section className="sk-control">
        <div className="sk-field">
          <span>查看班级</span>
          <Select
            allowClear
            value={selectedClassId}
            onChange={(next) => {
              setSelectedClassId(next)
              if (next === undefined) {
                setCalendar([])
              }
            }}
            placeholder="全部班级"
            className="sk-class-select"
            style={{ width: 260 }}
            popupMatchSelectWidth={300}
            options={resources.classes.map(classOption)}
          />
        </div>
        {activeTab === 'schedule' && (
          <div className="sk-field">
            <span>所在周</span>
            <DatePicker
              value={dayjs(weekStart)}
              onChange={(d: Dayjs | null) => setWeekStart(d ? d.format('YYYY-MM-DD') : '')}
              format="YYYY年MM月DD日"
            />
          </div>
        )}
        <span className="sk-note">
          {resources.assignments.filter(
            (item) => item.academic_year === academicYear && item.term === term,
          ).length }{' '}
          条任教关系
          {' · '}{validationIsCurrent ? '规则已通过' : '规则待校验'}
        </span>
      </section>

      <Tabs
        className="sk-tabs"
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as 'hours' | 'rules' | 'assignments' | 'schedule')}
        items={[
          {
            key: 'hours',
            label: '课时管理',
            children: (
              <CourseHoursPanel
                classes={resources.classes}
                subjects={resources.subjects}
                academicYear={academicYear}
                term={term}
                classId={selectedClassId}
              />
            ),
          },
          {
            key: 'rules',
            label: '建立规则',
            children: (
              <div className="st-rules">
                <TableCard>
                  <div className="zh-table-head">
                    <div className="zh-table-head-title">
                      <h2>排课规则模板</h2>
                      <p>课时在“课时管理”按班级维护，排课时段在“周格设置”统一维护；这里仅配置负载上限、教师约束、禁排时段与策略组合。</p>
                    </div>
                    <div className="zh-table-head-right">
                      <div className="zh-info-chip">
                        <span className="zh-info-chip-label">默认使用</span>
                        <strong>{activeRuleTemplate?.name || '—'}</strong>
                      </div>
                      <Button onClick={() => void openScopeRuleModal()}>
                        <Icon name="users" size={13} />
                        教师任教范围
                      </Button>
                    </div>
                  </div>
                  <Table<ScheduleRuleTemplate>
                    rowKey="id"
                    dataSource={ruleTemplates}
                    pagination={false}
                    size="middle"
                    scroll={{ x: 1100 }}
                    columns={[
                      {
                        title: '模板名称',
                        dataIndex: 'name',
                        width: 230,
                        fixed: 'left',
                        render: (name, record) => (
                          <div className="sk-rule-template-cell">
                            <span className="sk-rule-template-ico">
                              <Icon name="sparkles" size={14} />
                            </span>
                            <span className="sk-rule-template-copy">
                              <strong style={record.enabled === false ? { color: '#9ca3af' } : undefined}>{name}</strong>
                              <small>
                                {record.id.startsWith('builtin-') && <Tag color="blue">内置</Tag>}
                                {defaultRuleTemplateId === record.id && <Tag color="green">默认</Tag>}
                                {record.enabled === false && <Tag color="default">已停用</Tag>}
                              </small>
                            </span>
                          </div>
                        ),
                      },
                      {
                        title: '避免教师连堂',
                        dataIndex: ['config', 'avoid_consecutive_teacher_lessons'],
                        width: 124,
                        render: (v) => (
                          <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '不启用'}</Tag>
                        ),
                      },
                      {
                        title: '开启',
                        width: 76,
                        align: 'center',
                        render: (_, r) => (
                          <Switch
                            size="small"
                            checked={r.enabled !== false}
                            checkedChildren="开"
                            unCheckedChildren="关"
                            onChange={() => toggleRuleTemplate(r)}
                          />
                        ),
                      },
                      {
                        title: '启用策略',
                        width: 112,
                        render: (_, r) => (
                          <Tag color="purple">{r.config.strategy_codes.length} 项</Tag>
                        ),
                      },
                      {
                        title: '说明',
                        dataIndex: 'desc',
                        ellipsis: true,
                        render: (v, r) => {
                          const dims = `课时足额安排 · 同科自动分散 · 禁排${r.config.forbidden_slots.length}时段`
                          return v ? `${v}（${dims}）` : dims
                        },
                      },
                      {
                        title: '操作',
                        key: 'action',
                        width: 170,
                        fixed: 'right',
                        align: 'right',
                        render: (_, record) => (
                          <div className="st-rule-actions">
                            <Button
                              type="text"
                              size="small"
                              title={record.enabled === false ? '已停用，不可设为默认' : (defaultRuleTemplateId === record.id ? '默认规则' : '设为默认')}
                              icon={<Icon name="star" size={14} />}
                              disabled={record.enabled === false}
                              onClick={() => setDefaultRuleTemplateId(record.id)}
                            />
                            <Button
                              type="text"
                              size="small"
                              title="编辑"
                              icon={<Icon name="edit" size={14} />}
                              onClick={() => openRuleTemplateModal(record)}
                            />
                            <Popconfirm
                              title="删除规则模板"
                              description={record.id.startsWith('builtin-') ? '内置规则模板不可删除' : '删除后不可恢复，是否继续？'}
                              okText="删除"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                              disabled={record.id.startsWith('builtin-')}
                              onConfirm={() => deleteRuleTemplate(record)}
                            >
                              <Button
                                type="text"
                                size="small"
                                danger
                                title="删除"
                                disabled={record.id.startsWith('builtin-')}
                                icon={<Icon name="trash" size={14} />}
                              />
                            </Popconfirm>
                          </div>
                        ),
                      },
                    ]}
                    locale={{
                      emptyText: (
                        <EmptyState
                          icon="sparkles"
                          title="暂无规则模板"
                          desc="点击右上角「新建规则」创建组合模板"
                          height={240}
                        />
                      ),
                    }}
                  />
                </TableCard>
              </div>
            ),
          },
          {
            key: 'assignments',
            label: '任教关系',
            children: (
              <section className="sk-assign">
                <div className="zh-filter-row sk-assign-filters">
                  <div className="sk-assign-query">
                    <Input
                      className="sk-assignment-search"
                      value={assignKeyword}
                      onChange={(e) => setAssignKeyword(e.target.value)}
                      allowClear
                      placeholder="搜索学科、教师、班级或教室"
                    />
                    <Button type="primary" onClick={handleSearchAssignment}>查询</Button>
                    <Button onClick={resetAssignmentFilters}>重置</Button>
                    <span className="zh-filter-count">当前 {filteredAssignments.length} 条</span>
                  </div>
                  <div className="sk-assign-actions">
                    <Button type="primary" onClick={() => {
                      setTemplateGenIssues([])
                      void loadAutoGrades()
                      setTemplateGenVisible(true)
                    }}>自动生成</Button>
                  </div>
                </div>
                <TableCard>
                  <Table<TeachingAssignment>
                    rowKey="id"
                    columns={assignmentColumns}
                    dataSource={pagedAssignments}
                    pagination={{
                      current: assignPage,
                      pageSize: assignPageSize,
                      total: filteredAssignments.length,
                      onChange: (p, s) => {
                        setAssignPage(p)
                        setAssignPageSize(s)
                      },
                      showSizeChanger: true,
                      showTotal: (total) => `共 ${total} 条`,
                    }}
                    size="middle"
                    locale={{
                      emptyText: (
                      <EmptyState icon="users" title="当前班级暂无任教关系" desc="点击右上角新增任教关系" height={180} />
                      ),
                    }}
                  />
                </TableCard>
              </section>
            ),
          },
          {
            key: 'schedule',
            label: '日课表',
            children: (
              <section className="sk-surface sk-schedule-surface">
                <div className="sk-surface-head">
                  <div>
                    <div className="sk-surface-head-row">
                      <span className="sk-class-pill">{selectedClassName}</span>
                      <Tag color={activeRuleTemplate?.id?.startsWith('builtin-') ? 'blue' : 'green'}>
                        规则：{activeRuleTemplate?.name || '—'}
                      </Tag>
                      <Tag color="purple">{academicYear} 学年 · 第 {term} 学期</Tag>
                      <Tag color="default" style={{ whiteSpace: 'nowrap' }}>{weekStart} 所在周</Tag>
                    </div>
                    <h2>{selectedClassName} · 日课表</h2>
                  </div>
                  <div className="sk-calendar-actions">
                    <Select
                      style={{ width: 220 }}
                      value={defaultRuleTemplateId || undefined}
                      placeholder="选择启用模板"
                      onChange={(v) => {
                        const tpl = ruleTemplates.find(t => t.id === v)
                        if (tpl) {
                          // 切换下拉 = 开启该模板（其余自动停用），保持互斥
                          setDefaultRuleTemplateId(tpl.id)
                          persistRuleTemplates(ruleTemplates.map(t => t.id === tpl.id
                            ? { ...t, enabled: true, updated_at: new Date().toISOString() }
                            : { ...t, enabled: false }))
                          void applyRuleTemplateAsConditions(tpl)
                        }
                      }}
                      options={ruleTemplates.filter(t => t.enabled !== false).map(t => ({
                        label: t.name + (defaultRuleTemplateId === t.id ? '（当前）' : ''),
                        value: t.id,
                      }))}
                    />
                    <Dropdown
                      disabled={generating || scheduleVersions.length === 0}
                      destroyPopupOnHide
                      menu={{
                        items: (
                          scheduleVersions.length === 0
                            ? [{ key: 'empty', label: '（暂无历史版本，生成课后自动记录）', disabled: true }]
                            : scheduleVersions.map((v) => ({
                                key: String(v.version_id),
                                label: (
                                  <div style={{ minWidth: 280 }}>
                                    <div style={{ fontWeight: 600 }}>{v.label}</div>
                                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                                      {v.class_count} 个班 · {v.lesson_count} 节课 · {v.academic_year}学年 第{v.term}学期
                                    </div>
                                  </div>
                                ),
                                onClick: () => void restoreScheduleVersion(v),
                              }))
                        ) as MenuProps['items'],
                      }}
                    >
                      <Button disabled={generating} loading={versionsLoading}>
                        课表版本
                        {!versionsLoading && scheduleVersions.length > 0 ? (
                          <span style={{ marginLeft: 4, fontSize: 12, color: '#6b7280' }}>（{scheduleVersions.length}）</span>
                        ) : null}
                      </Button>
                    </Dropdown>
                    <Button
                      type="primary"
                      loading={generating}
                      disabled={generating}
                      icon={!generating ? <Icon name="sparkles" size={14} /> : undefined}
                      onClick={openGenerationRulePreview}
                    >
                      {generating ? '正在生成' : '生成课表'}
                    </Button>
                    <Button onClick={() => setGridConfigVisible(true)}>周格设置</Button>
                    <Button onClick={() => window.print()}>
                      <Icon name="printer" size={14} />
                      打印
                    </Button>
                  </div>
                </div>
                <div className="sk-schedule-overview">
                  <div className="sk-schedule-overview-copy">
                    <span className="sk-schedule-overview-label">WEEKLY RHYTHM</span>
                    <strong>本周课程节奏</strong>
                    <span>按教学日查看课程分布，颜色仅用于快速识别学科类别。</span>
                  </div>
                  <div className="sk-schedule-legend" aria-label="学科颜色图例">
                    <span><i className="sk-legend-swatch language" />语言</span>
                    <span><i className="sk-legend-swatch math" />数学</span>
                    <span><i className="sk-legend-swatch science" />理科</span>
                    <span><i className="sk-legend-swatch humanities" />文科</span>
                    <span><i className="sk-legend-swatch activity" />活动</span>
                  </div>
                </div>
                {loading ? (
                  <div className="sk-schedule-loading">
                    <EmptyState icon="calendar" title="课表加载中…" height={320} />
                  </div>
                ) : (
                  calendar.length ? (
                    <ScheduleGrid
                      entries={calendar}
                      periods={gridConfig.periods_per_day}
                      days={gridConfig.days}
                      dailyPeriods={gridConfig.daily_periods}
                      showEvening
                      eveningStartPeriod={gridConfig.evening_start_period}
                      dateMode
                      weekStart={weekStart}
                      onLessonContextMenu={openAdjustment}
                    />
                  ) : (
                    <EmptyState
                      icon="calendar"
                      title="当前班级还没有课表"
                      desc="请先配置任教关系并生成课表。"
                      height={260}
                    />
                  )
                )}
              </section>
            ),
          },
        ].sort((left, right) => {
          const order = ['hours', 'assignments', 'rules', 'schedule']
          return order.indexOf(left.key) - order.indexOf(right.key)
        })}
      />

      <Modal title="公共周格设置" open={gridConfigVisible} onCancel={() => setGridConfigVisible(false)} onOk={() => void saveGridConfig()} width={760}>
        <Form layout="vertical">
          <p style={{ color: '#667085', marginTop: 0 }}>逐日设置正式课节数。未启用的日期填 0；自动排课会把超过当日节数的时段视为禁排。</p>
          <div className="sk-weekday-period-grid">
            {WEEKDAY_NAMES.map((name, index) => (
              <div key={name} className="sk-weekday-period-cell">
                <strong>{name}</strong>
                <InputNumber min={0} max={12} value={gridConfig.daily_periods[index]} addonAfter="节" onChange={(v) => setGridConfig((current) => {
                  const dailyPeriods = [...current.daily_periods]
                  dailyPeriods[index] = v ?? 0
                  const active = dailyPeriods.map((count, day) => count > 0 ? day + 1 : 0)
                  return { ...current, daily_periods: dailyPeriods, days: Math.max(...active), periods_per_day: Math.max(...dailyPeriods) }
                })} />
              </div>
            ))}
          </div>
          <Space size="large">
            <Form.Item label="启用晚自习"><Switch checked={gridConfig.enable_evening} onChange={(v) => setGridConfig((x) => ({
              ...x,
              enable_evening: v,
              evening_start_period: null,
              evening_daily_periods_odd: v ? x.evening_daily_periods_odd : [0, 0, 0, 0, 0, 0, 0],
              evening_daily_periods_even: v ? x.evening_daily_periods_even : [0, 0, 0, 0, 0, 0, 0],
            }))} /></Form.Item>
            <Form.Item label="首周"><Select value={gridConfig.first_week_parity} style={{ width: 100 }} options={[{ value: 'odd', label: '单周' }, { value: 'even', label: '双周' }]} onChange={(v) => setGridConfig((x) => ({ ...x, first_week_parity: v }))} /></Form.Item>
          </Space>
          {gridConfig.enable_evening && <div className="sk-grid-help sk-evening-time-note">晚自习作为独立时段，自动接在当天最后一节正式课之后；这里仅配置每周各日可安排的晚课节数。</div>}
          {gridConfig.enable_evening && <Form.Item label="单周 / 双周每天晚自习节数">
            <div className="sk-evening-profile">
              {([
                ['单周', 'evening_daily_periods_odd'],
                ['双周', 'evening_daily_periods_even'],
              ] as const).map(([label, field]) => <div className="sk-evening-profile-row" key={field}>
                <strong>{label}</strong>
                {WEEKDAY_NAMES.slice(0, gridConfig.days).map((day, index) => <InputNumber key={day} aria-label={`${label}${day}晚自习节数`} min={0} max={1} value={gridConfig[field][index]} onChange={(v) => setGridConfig((current) => {
                  const profile = [...current[field]]
                  profile[index] = v ?? 0
                  return { ...current, [field]: profile }
                })} />)}
                <strong>{gridConfig[field].reduce((sum, count) => sum + count, 0)} 节</strong>
              </div>)}
            </div>
          </Form.Item>}
          {gridConfig.enable_evening && <div className="sk-grid-help sk-evening-business-note">
            晚自习每天只有 1 节。请在“课时管理”中填写晚课 0、0.5 或 1：0.5 再选择单周或双周；生成课表时会自动带出对应任教关系中的坐班老师。未配置晚课的剩余格显示为自主学习。
          </div>}
          <Form.Item label="学期首周周一"><DatePicker value={gridConfig.term_start_monday ? dayjs(gridConfig.term_start_monday) : null} onChange={(v) => setGridConfig((x) => ({ ...x, term_start_monday: v?.format('YYYY-MM-DD') ?? null }))} /></Form.Item>
        </Form>
      </Modal>

      {/* 配置任教关系 */}
      <Modal
        title={assignmentModalTitle}
        open={assignmentVisible}
        onCancel={() => setAssignmentVisible(false)}
        onOk={saveAssignment}
        okText="保存配置"
        cancelText="取消"
        confirmLoading={savingAssignment}
        width={500}
      >
        <Form layout="vertical" className="sk-form-grid">
          <Form.Item label="安排类型" required>
            <Select
              value={assignmentForm.mode || 'subject'}
              onChange={(value: 'subject' | 'activity') => setAssignmentForm((prev) => ({ ...prev, mode: value, teacher_id: undefined, subject_id: undefined }))}
              options={[{ value: 'subject', label: '学科课（绑定任课教师）' }, { value: 'activity', label: '活动课（可不绑定教师）' }]}
            />
          </Form.Item>
          <Form.Item label="班级" required>
            <Select
              value={assignmentForm.class_id}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, class_id: v }))}
              options={resources.classes.map(classOption)}
            />
          </Form.Item>
          {assignmentIsActivity ? <Form.Item label="活动类型" required>
            <Select
              value={assignmentForm.subject_id}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, subject_id: v }))}
              options={activitySubjects.map((item) => ({ label: item.name, value: item.id }))}
            />
          </Form.Item> : <Form.Item label="教师" required>
            <Select
              value={assignmentForm.teacher_id}
              onChange={(v) => setAssignmentForm((prev) => {
                const subjectIds = v ? resources.teacher_subject_ids?.[String(v)] ?? [] : []
                return { ...prev, teacher_id: v, subject_id: subjectIds.length === 1 ? subjectIds[0] : undefined }
              })}
              options={resources.teachers.map((item) => {
                  const subjectNames = (resources.teacher_subject_ids?.[String(item.id)] ?? [])
                    .map((id) => resources.subjects.find((subject) => subject.id === id)?.name)
                    .filter(Boolean)
                  return { label: subjectNames.length ? `${item.name}（${subjectNames.join('、')}）` : `${item.name}（未关联学科组）`, value: item.id }
                })}
            />
          </Form.Item>}
          <div className="sk-assignment-hours-note">
            <strong>{assignmentIsActivity ? '活动安排规则' : '学科由组织关系自动确定'}</strong>
            <span>{assignmentIsActivity
              ? assignmentSubjectName === '班会' ? '班会自动绑定本班班主任，不计入班主任的学科课时。' : '活动课可以不绑定教师，不计入教师学科课量。'
              : assignmentSubjectName
              ? `已识别学科：${assignmentSubjectName}`
              : assignmentForm.teacher_id && assignmentTeacherSubjectIds.length > 1
                ? '该教师关联多个学科组，请先在人员管理中明确唯一学科组。'
                : assignmentForm.teacher_id
                  ? '该教师尚未关联学科组，请先在人员管理中维护。'
                  : '选择教师后，系统根据其所属学科组自动带出学科。'}</span>
          </div>
          <div className="sk-assignment-hours-note">
            <strong>课时由「课时管理」维护</strong>
            <span>先保存任教关系，再到课时管理设置每周课时；单双周课程也在那里配置。</span>
          </div>
        </Form>
        <Form layout="vertical">
          <Form.Item label="固定教室（可选）">
            <Input
              value={assignmentForm.room}
              onChange={(e) => setAssignmentForm((prev) => ({ ...prev, room: e.target.value }))}
              placeholder="例如：高一教学楼 302"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新增教师账号 */}
      <Modal
        title="新增教师账号"
        open={teacherVisible}
        onCancel={() => setTeacherVisible(false)}
        onOk={saveTeacher}
        okText="创建教师"
        cancelText="取消"
        confirmLoading={savingTeacher}
        width={440}
      >
        <Form layout="vertical">
          <Form.Item label="教师姓名" required>
            <Input
              value={teacherForm.name}
              onChange={(e) => setTeacherForm((prev) => ({ ...prev, name: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="手机号 / 登录账号" required>
            <Input
              value={teacherForm.phone}
              onChange={(e) => setTeacherForm((prev) => ({ ...prev, phone: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="初始密码" required>
            <Input.Password
              value={teacherForm.password}
              onChange={(e) => setTeacherForm((prev) => ({ ...prev, password: e.target.value }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        className="sk-scope-rule-modal"
        title={`教师搭班规则 · ${academicYear} · 第${term}学期`}
        open={scopeRuleVisible}
        onCancel={() => setScopeRuleVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setScopeRuleVisible(false)}>关闭</Button>,
        ]}
        zIndex={1100}
        width={960}
        style={{ top: 60 }}
        bodyStyle={{ maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' }}
      >
        <div className="sk-scope-header">
          <div className="sk-scope-filter">
            <Select
              allowClear
              value={scopeRuleForm.teacher_id}
              onChange={(value) => setScopeRuleForm((prev) => ({ ...prev, teacher_id: value }))}
              popupMatchSelectWidth={false}
              placeholder="选择教师"
              style={{ width: 180 }}
              options={resources.teachers.map((item) => ({ label: item.name, value: item.id }))}
            />
            <Select
              allowClear
              value={scopeRuleForm.class_id}
              onChange={(value) => setScopeRuleForm((prev) => ({ ...prev, class_id: value }))}
              popupMatchSelectWidth={false}
              placeholder="选择班级"
              style={{ width: 180 }}
              options={resources.classes.map(classOption)}
            />
            <Select
              allowClear
              value={scopeRuleForm.mode}
              onChange={(value?: 'allow' | 'deny') => setScopeRuleForm((prev) => ({ ...prev, mode: value }))}
              placeholder="授课范围"
              style={{ width: 150 }}
              options={[{ label: '固定教授（必须带）', value: 'allow' }, { label: '禁止教授', value: 'deny' }]}
            />
            <Button type="primary" onClick={queryScopeRules}>查询</Button>
            <Button onClick={resetScopeRuleQuery}>重置</Button>
          </div>
          <div className="sk-scope-actions">
            <Button type="primary" onClick={openNewScopeRuleForm}>
              新建规则
            </Button>
          </div>
        </div>
        <TableCard>
          <Table<TeacherScopeRule>
            rowKey={(record) => `${record.teacher_id}-${record.class_id}`}
            size="middle"
            dataSource={visibleScopeRules}
            pagination={{
              pageSize: 8,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 条规则`,
            }}
            locale={{
              emptyText: (
                <EmptyState
                  height={180}
                  title="暂无搭班规则"
                  desc="点击右上角“新建规则”创建教师与班级的授课约束"
                />
              ),
            }}
            columns={[
              { title: '教师', dataIndex: 'teacher_name', width: 140 },
              { title: '班级', dataIndex: 'class_name', width: 160 },
              {
                title: '授课范围',
                dataIndex: 'mode',
                width: 140,
                render: (value: TeacherScopeRule['mode']) => value === 'allow' ? (
                  <Tag color="green">固定教授</Tag>
                ) : (
                  <Tag color="red">排除教授</Tag>
                ),
              },
              {
                title: '说明',
                key: 'desc',
                ellipsis: true,
                render: (_, record) => `${record.teacher_name || '教师'} · ${record.mode === 'allow' ? '固定教授' : '不教授'} · ${record.class_name || '班级'}`,
              },
              {
                title: '操作',
                key: 'action',
                width: 120,
                align: 'right',
                render: (_, record) => (
                  <Space size={4}>
                    <Button type="link" size="small" onClick={() => openEditScopeRuleForm(record)}>编辑</Button>
                    <Popconfirm title="确认删除该条搭班规则？" onConfirm={() => {
                      setScopeRules((prev) => prev.filter((item) => item !== record))
                      void schedulingApi.saveScopeRules({ academic_year: academicYear, term, rules: scopeRules.filter((item) => item !== record) })
                    }}>
                      <Button type="link" size="small" danger>删除</Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        </TableCard>
      </Modal>

      <Modal
        title={editingScopeRuleKey ? '编辑搭班规则' : '新建搭班规则'}
        open={scopeRuleFormVisible}
        onOk={submitScopeRuleForm}
        onCancel={closeScopeRuleForm}
        okText={editingScopeRuleKey ? '保存' : '创建'}
        cancelText="取消"
        width={520}
        zIndex={1200}
        destroyOnClose
      >
        <div className="sk-scope-form-modal">
          <label className="sk-label">
            教师
            <Select
              value={scopeRuleForm.teacher_id}
              onChange={(value) => setScopeRuleForm((prev) => ({ ...prev, teacher_id: value }))}
              placeholder="选择教师"
              showSearch
              optionFilterProp="label"
              options={resources.teachers.map((item) => ({ label: item.name, value: item.id }))}
            />
          </label>
          <label className="sk-label">
            班级
            <Select
              value={scopeRuleForm.class_id}
              onChange={(value) => setScopeRuleForm((prev) => ({ ...prev, class_id: value }))}
              placeholder="选择班级"
              showSearch
              optionFilterProp="label"
              options={resources.classes.map(classOption)}
            />
          </label>
          <label className="sk-label">
            授课范围
            <Select
              value={scopeRuleForm.mode}
              onChange={(value: 'allow' | 'deny') => setScopeRuleForm((prev) => ({ ...prev, mode: value }))}
              options={[{ label: '固定教授（必须带）', value: 'allow' }, { label: '禁止教授', value: 'deny' }]}
            />
          </label>
          <div className="sk-scope-summary">
            组合效果：<b>{scopeRuleForm.mode === 'deny' ? '排除教授' : '固定教授'}</b>
          </div>
        </div>
      </Modal>

      {/* “模版生成任教关系”已移除；任教关系统一通过课时管理后的自动生成入口处理。 */}

      {/* 自动生成：按课时方案一键生成任教关系 */}
      <Modal
        title={`自动生成任教关系 · ${academicYear} · 第${term}学期`}
        open={templateGenVisible}
        onCancel={() => setTemplateGenVisible(false)}
        width={560}
        footer={<Space>
          <Button onClick={() => setTemplateGenVisible(false)}>取消</Button>
          <Button type="primary" loading={templateGenLoading} onClick={() => void runTemplateGenerate()}>生成</Button>
        </Space>}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <label className="sk-label">
            课时方案
            <Select
              value={templateGenPlan}
              onChange={(value) => setTemplateGenPlan(value)}
              style={{ width: '100%' }}
              options={allPeriodPlans.map((item) => ({
                label: `${item.name}（${Object.values(item.rules).reduce((sum, periods) => sum + periods, 0)} 节/周）`,
                value: item.name,
              }))}
            />
          </label>
          <label className="sk-label">
            生成范围
            <Select
              mode="multiple"
              allowClear
              value={autoGradeIds}
              onChange={(value: number[]) => setAutoGradeIds(value)}
              style={{ width: '100%' }}
              options={grades.map((item) => ({ label: item.name, value: item.id }))}
              placeholder="全部年级（不选 = 全校所有班级）"
            />
          </label>
          {templateGenIssues.length > 0 && (
            <div className="sk-auto-teaching-result is-failed" role="status">
              <div className="sk-auto-teaching-head">
                <strong>校验未通过</strong>
                <span>请调整方案或上限后重试</span>
              </div>
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                {templateGenIssues.map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            </div>
          )}
          <p className="zh-page-desc" style={{ margin: 0 }}>按所选课时方案直接生成全部任教关系；先自动校验，通过后才会写入，不通过会在此列出原因。</p>
        </Space>
      </Modal>

      {/* 规则模板：新建 / 编辑 */}
      <Modal
        title={editingRuleTemplateId ? '编辑规则模板' : '新建规则模板'}
        open={ruleTemplateModalOpen}
        onCancel={() => setRuleTemplateModalOpen(false)}
        onOk={saveRuleTemplate}
        okText="保存规则"
        cancelText="取消"
        width={760}
        maskClosable={false}
        destroyOnClose
      >
        <Form layout="vertical">
          <Form.Item label="规则模板名称" required>
            <Input
              placeholder="如：高三冲刺排课、艺体生专用、学科日集中排"
              value={ruleTemplateForm.name}
              onChange={(e) => setRuleTemplateForm(prev => ({ ...prev, name: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="简要说明">
            <Input.TextArea
              autoSize={{ minRows: 2, maxRows: 4 }}
              placeholder="这个模板的典型适用场景 / 亮点"
              value={ruleTemplateForm.desc}
              onChange={(e) => setRuleTemplateForm(prev => ({ ...prev, desc: e.target.value }))}
            />
          </Form.Item>
            <div className="sk-template-editor-card">
            <div className="sk-template-source-note">
              <strong>科目课时已确定</strong>
              <span>课时统一来自“课时管理”，排课时段统一来自“周格设置”；这里集中维护排课约束。</span>
            </div>
            <div className="sk-template-editor-head">
              <div>
                <h3>模板规则内容</h3>
                <p>模板只配置负载、完整度、教师约束、禁排与策略；科目课时和排课时段分别由“课时管理”“周格设置”维护。</p>
              </div>
              <Space>
                <Button
                  onClick={() => {
                    setConditions(JSON.parse(JSON.stringify(ruleTemplateForm.config)))
                    setValidation(null)
                    setValidatedSignature('')
                    setConditionVisible(true)
                  }}
                >
                  在规则设计器中编辑
                </Button>
                <Button
                  type="primary"
                  onClick={() => {
                    setRuleTemplateForm(prev => ({
                      ...prev,
                      config: JSON.parse(JSON.stringify(conditions)),
                    }))
                    message.success('已将当前规则设计器内容同步到模板')
                  }}
                >
                  同步当前规则到模板
                </Button>
              </Space>
            </div>
            <dl className="sk-template-dim">
              <div><dt>晚自习时间容量</dt><dd>{ruleTemplateForm.config.enable_evening ? `单周 ${(ruleTemplateForm.config.evening_daily_periods_odd ?? []).reduce((sum, count) => sum + count, 0)} 节 / 双周 ${(ruleTemplateForm.config.evening_daily_periods_even ?? []).reduce((sum, count) => sum + count, 0)} 节` : '不启用'}</dd></div>
              <div><dt>课时安排</dt><dd>按课时管理足额排课</dd></div>
              <div><dt>同科分布</dt><dd>算法自动分散</dd></div>
              <div><dt>任教关系</dt><dd>按已配置关系校验</dd></div>
              <div><dt>禁排时段</dt><dd>{ruleTemplateForm.config.forbidden_slots.length} 个</dd></div>
              <div><dt>启用策略</dt><dd>{ruleTemplateForm.config.strategy_codes.length} 项</dd></div>
            </dl>
          </div>
          <div className="sk-help">
            <strong>使用流程：</strong>先在「周格设置」维护排课时段，再点「在规则设计器中编辑」设置约束并校验 → 「同步当前规则到模板」→ 「保存规则」。
          </div>
        </Form>
      </Modal>

      <RuleDesigner
        open={conditionVisible}
        value={conditions}
        strategies={strategies}
        validation={validation}
        validating={validatingRules}
        issueText={issueText}
        onChange={updateConditions}
        onValidate={validateRules}
        onClose={() => setConditionVisible(false)}
        gridConfig={gridConfig}
      />

      <RuleDesigner
        open={generationRuleVisible}
        value={activeRuleTemplate?.config || conditions}
        strategies={strategies}
        validation={null}
        validating={false}
        issueText={issueText}
        onChange={() => undefined}
        onValidate={() => undefined}
        onClose={() => setGenerationRuleVisible(false)}
        gridConfig={gridConfig}
        readOnly
        onConfirm={() => {
          setGenerationRuleVisible(false)
          void generateAll()
        }}
      />

      <Modal
        title={adjustmentEntry ? `${adjustmentEntry.subject_name || '课程'} · ${adjustmentEntry.teacher_name || '未安排教师'} · 周${['一', '二', '三', '四', '五', '六', '日'][adjustmentEntry.weekday - 1]}第${adjustmentEntry.period}节` : '课程调整'}
        open={Boolean(adjustmentEntry)}
        onCancel={() => setAdjustmentEntry(undefined)}
        footer={null}
        centered
        width={620}
      >
        <div className="sk-adjustment-panel">
          <Tabs
            activeKey={adjustmentTab}
            onChange={(key) => setAdjustmentTab(key as 'move' | 'substitute')}
            items={[
              {
                key: 'move',
                label: '调课（换时段）',
                children: (
                  <>
                    <p>仅显示当前课时之后的时段；灰色时段表示存在班级或教师冲突。</p>
                    <div className="sk-adjustment-options">
                      {adjustmentLoading ? <EmptyState icon="calendar" title="正在计算可调时段…" height={160} /> : adjustmentOptions.map((option) => (
                        <Button
                          key={`${option.weekday}-${option.period}`}
                          disabled={!option.available || movingSchedule}
                          loading={movingSchedule && option.available}
                          onClick={() => void moveEntry(option)}
                          className={!option.available ? 'is-unavailable' : ''}
                        >
                          周{['一', '二', '三', '四', '五', '六', '日'][option.weekday - 1]} · 第{option.period}节
                          <span>{option.reason}</span>
                        </Button>
                      ))}
                    </div>
                  </>
                ),
              },
              {
                key: 'substitute',
                label: '代课（换老师）',
                children: (
                  <>
                    <p>本学期教该学科、且此时段没课的老师；按当前周课时从少到多排列，适合病假、事假临时顶课。</p>
                    <div className="sk-adjustment-options">
                      {adjustmentLoading ? <EmptyState icon="user" title="正在查询可代课教师…" height={160} /> : substituteOptions.length === 0 ? (
                        <EmptyState icon="user" title="没有可代课的教师" desc="该学科没有其他任教教师" height={140} />
                      ) : substituteOptions.map((option) => (
                        <Button
                          key={option.teacher_id}
                          disabled={!option.available || movingSchedule}
                          loading={movingSchedule && option.available}
                          onClick={() => void applySubstitute(option)}
                          className={!option.available ? 'is-unavailable' : ''}
                        >
                          {option.teacher_name}
                          <span>{option.available ? `周 ${option.weekly_lessons} 节 · 可代课` : option.reason}</span>
                        </Button>
                      ))}
                    </div>
                  </>
                ),
              },
            ]}
          />
        </div>
      </Modal>
    </div>
  )
}
