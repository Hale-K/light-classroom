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
  SchedulingResources,
  ScheduleValidationIssue,
  ScheduleValidationResult,
  ScheduleVersionSummary,
  TeacherScopeRule,
  TeachingAssignment,
} from '@/types'
import RuleDesigner from './RuleDesigner'
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

const GEN_STEPS = [
  { code: 'validating', label: '校验资源' },
  { code: 'generating', label: '初排与冲突修复' },
  { code: 'refreshing', label: '保存并刷新' },
  { code: 'done', label: '生成完成' },
] as const
type GenStage = 'idle' | (typeof GEN_STEPS)[number]['code'] | 'blocked' | 'error'

/** 自动任教关系编排结果中的单条计划行 */
type AutoTeachingPlanRow = Awaited<ReturnType<typeof schedulingApi.autoTeaching>>['plan'][number]

interface AssignmentForm {
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

  const [activeTab, setActiveTab] = useState<'rules' | 'assignments' | 'schedule'>('rules')
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
  const [autoTeachingVisible, setAutoTeachingVisible] = useState(false)
  const [scopeRules, setScopeRules] = useState<TeacherScopeRule[]>([])
  const [scopeRuleForm, setScopeRuleForm] = useState<Partial<TeacherScopeRule>>({ mode: 'allow', weekly_periods: 4 })
  const [scopeRuleFilter, setScopeRuleFilter] = useState<Partial<TeacherScopeRule>>({})
  const [scopeRuleFormVisible, setScopeRuleFormVisible] = useState(false)
  const [editingScopeRuleKey, setEditingScopeRuleKey] = useState<string | undefined>()
  const [autoTeachingResult, setAutoTeachingResult] = useState<Awaited<ReturnType<typeof schedulingApi.autoTeaching>>>()
  const [autoTeachingLogsVisible, setAutoTeachingLogsVisible] = useState(false)
  const [autoTeachingLoading, setAutoTeachingLoading] = useState(false)
  const autoWeeklyPeriods = 4
  const [autoTeachingPlan, setAutoTeachingPlan] = useState<string | undefined>()
  const [autoSubjectRules, setAutoSubjectRules] = useState<Array<{ subject_id: number; weekly_periods: number }>>([])
  const [autoSubjectTeacherLimits, setAutoSubjectTeacherLimits] = useState<Array<{ subject_id: number; max_weekly_periods: number }>>([])
  const [grades, setGrades] = useState<Grade[]>([])
  const [autoGradeIds, setAutoGradeIds] = useState<number[]>([])
  // 课时方案：内置标准方案 + 本地自定义方案，一键填充学科课时规则
  const PERIOD_PLANS_KEY = 'scheduling.period_plans.v1'
  const BUILTIN_PERIOD_PLANS: Array<{ name: string; rules: Record<string, number> }> = [
    { name: '标准方案', rules: { 语文: 5, 数学: 5, 英语: 5, 物理: 3, 化学: 3, 生物: 2, 政治: 2, 历史: 2, 地理: 2, 体育: 1 } },
  ]
  const [periodPlans, setPeriodPlans] = useState<Array<{ name: string; rules: Record<string, number> }>>([])
  const allPeriodPlans = useMemo(() => [...BUILTIN_PERIOD_PLANS, ...periodPlans], [periodPlans])
  // 模版生成：选课时方案直接生成任教关系
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
    max_classes_per_teacher: 3,
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
  const DEFAULT_RULE_CONFIG: ScheduleRuleConfig = {
    days: 5,
    periods_per_day: 6,
    max_class_lessons_per_day: 6,
    max_teacher_lessons_per_day: 6,
    max_teacher_weekly_periods: 30,
    max_same_subject_per_day: 2,
    require_full_week: true,
    max_classes_per_teacher: 3,
    avoid_consecutive_teacher_lessons: true,
    forbidden_slots: [],
    strategy_codes: ['cross_day_variety', 'class_compact', 'daily_balance', 'cross_class_gap_repair', 'random_tiebreak'],
  }
  const buildInTemplates = (): ScheduleRuleTemplate[] => [
    {
      id: 'builtin-balanced',
      name: '常规均衡排课',
      desc: '每日最多 6 节 / 同科最多 2 节 / 教师跨班不超过 3 个 / 避免连堂',
      enabled: true,
      config: DEFAULT_RULE_CONFIG,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: 'builtin-intensive',
      name: '集中紧凑排课',
      desc: '同科 2 节尽量集中、班级尽量紧凑、用于半天学科日',
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
      // 兼容旧数据：无 enabled 字段视为启用
      return list.map((t) => ({ ...t, enabled: t.enabled !== false }))
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

  const generationPayload = (config: ScheduleRuleConfig = conditions) => ({
    academic_year: academicYear,
    term,
    days: config.days,
    periods_per_day: config.periods_per_day,
    max_class_lessons_per_day: config.max_class_lessons_per_day,
    max_teacher_lessons_per_day: config.max_teacher_lessons_per_day,
    max_teacher_weekly_periods: config.max_teacher_weekly_periods,
    max_same_subject_per_day: config.max_same_subject_per_day,
    require_full_week: config.require_full_week,
    max_classes_per_teacher: config.max_classes_per_teacher,
    avoid_consecutive_teacher_lessons: config.avoid_consecutive_teacher_lessons,
    forbidden_slots: config.forbidden_slots.map(
      (slot) => slot.split('-').map(Number) as [number, number],
    ),
    strategy_codes: config.strategy_codes,
  })

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
      if (issue.code === 'teacher_class_count_exceeded') {
        return `${name}承担 ${issue.requested} 个班，当前上限 ${issue.capacity} 个班`
      }
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

  const addAutoSubjectRule = () => {
    const candidate = resources.subjects.find((item) => (
      !resources.teaching_track_subject_ids?.includes(item.id) &&
      !autoSubjectRules.some((rule) => rule.subject_id === item.id)
    ))
    if (!candidate) {
      message.warning('没有可添加的学科')
      return
    }
    setAutoSubjectRules((current) => [...current, { subject_id: candidate.id, weekly_periods: autoWeeklyPeriods }])
    setAutoSubjectTeacherLimits((current) => [...current, { subject_id: candidate.id, max_weekly_periods: autoMaxWeeklyPeriods }])
    setAutoTeachingResult(undefined)
  }

  const updateAutoRuleSubject = (prevSubjectId: number, subjectId: number) => {
    setAutoSubjectRules((current) => current.map((item) => (item.subject_id === prevSubjectId ? { ...item, subject_id: subjectId } : item)))
    setAutoSubjectTeacherLimits((current) => current.map((item) => (item.subject_id === prevSubjectId ? { ...item, subject_id: subjectId } : item)))
    setAutoTeachingResult(undefined)
  }

  const updateAutoRulePeriods = (subjectId: number, weeklyPeriods: number) => {
    setAutoSubjectRules((current) => current.map((item) => (item.subject_id === subjectId ? { ...item, weekly_periods: weeklyPeriods } : item)))
    setAutoTeachingResult(undefined)
  }

  const updateAutoRuleLimit = (subjectId: number, maxWeeklyPeriods: number) => {
    setAutoSubjectTeacherLimits((current) => current.map((item) => (item.subject_id === subjectId ? { ...item, max_weekly_periods: maxWeeklyPeriods } : item)))
    setAutoTeachingResult(undefined)
  }

  // 体育学科：规则设计器「体育课节数」配置在打开弹框时同步为一条规则行
  const peSubject = resources.subjects.find((item) => item.name.includes('体育') && !resources.teaching_track_subject_ids?.includes(item.id))

  const periodPlanEntries = (plan: { name: string; rules: Record<string, number> }) => Object.entries(plan.rules)
    .map(([subjectName, weeklyPeriods]) => {
      const subject = resources.subjects.find((item) => item.name === subjectName && !resources.teaching_track_subject_ids?.includes(item.id))
      return subject ? { subject_id: subject.id, weekly_periods: weeklyPeriods } : null
    })
    .filter((item): item is { subject_id: number; weekly_periods: number } => item !== null)

  const applyPeriodPlan = (plan: { name: string; rules: Record<string, number> }) => {
    const entries = periodPlanEntries(plan)
    if (!entries.length) {
      message.warning('方案中没有可用学科')
      return
    }
    setAutoSubjectRules(entries)
    setAutoSubjectTeacherLimits(entries.map((item) => ({ subject_id: item.subject_id, max_weekly_periods: autoMaxWeeklyPeriods })))
    setAutoTeachingPlan(plan.name)
    setAutoTeachingResult(undefined)
  }

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
        days: conditions.days,
        periods_per_day: conditions.periods_per_day,
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
      message.error(error instanceof Error ? error.message : '模版生成失败')
    } finally {
      setTemplateGenLoading(false)
    }
  }

  const saveCurrentPeriodPlan = () => {
    if (!autoSubjectRules.length) {
      message.warning('请先添加课时规则再保存方案')
      return
    }
    const name = window.prompt('方案名称', `方案 ${periodPlans.length + 1}`)
    if (!name) return
    const rules: Record<string, number> = {}
    for (const rule of autoSubjectRules) {
      const subject = resources.subjects.find((item) => item.id === rule.subject_id)
      if (subject) rules[subject.name] = rule.weekly_periods
    }
    const next = [...periodPlans.filter((item) => item.name !== name), { name, rules }]
    setPeriodPlans(next)
    try {
      localStorage.setItem(PERIOD_PLANS_KEY, JSON.stringify(next))
    } catch {
      // 本地存储不可用时方案仅本次会话有效
    }
    message.success(`方案「${name}」已保存`)
  }

  const runAutoTeaching = async (execute: boolean) => {
    if (autoSubjectRules.length === 0) {
      message.warning('未配置课时方案:10 科默认每周 4 节共 40 节,会超出班级周容量(每日上限 × 天数)。请先在「课时方案」选择或用 + 添加规则')
      return
    }
    setAutoTeachingLoading(true)
    setAutoTeachingLogsVisible(false)
    try {
      await schedulingApi.saveScopeRules({ academic_year: academicYear, term, rules: scopeRules })
      const classIds = autoGradeIds.length > 0
        ? resources.classes.filter((item) => autoGradeIds.includes(item.grade_id)).map((item) => item.id)
        : undefined
      const result = await schedulingApi.autoTeaching({
        academic_year: academicYear,
        term,
        class_ids: classIds,
        weekly_periods: autoWeeklyPeriods,
        max_weekly_periods: autoMaxWeeklyPeriods,
        subject_period_rules: autoSubjectRules,
        subject_teacher_limits: autoSubjectTeacherLimits,
        execute,
        days: conditions.days,
        periods_per_day: conditions.periods_per_day,
        forbidden_slots: conditions.forbidden_slots.map(
          (slot) => slot.split('-').map(Number) as [number, number],
        ),
        max_class_lessons_per_day: conditions.max_class_lessons_per_day,
        max_teacher_lessons_per_day: conditions.max_teacher_lessons_per_day,
        max_same_subject_per_day: conditions.max_same_subject_per_day,
      })
      setAutoTeachingResult(result)
      if (execute) {
        setValidation(null)
        setValidatedSignature('')
        await loadResources()
        message.success(`已${result.created_count ? `生成 ${result.created_count} 条` : '完成'}自动任教关系`)
        setAutoTeachingVisible(false)
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '自动生成任教关系失败')
    } finally {
      setAutoTeachingLoading(false)
    }
  }

  const loadTable = async () => {
    if (!selectedClassId) return
    if (!generating) setLoading(true)
    try {
      const c = await schedulingApi.calendar({
        class_id: selectedClassId,
        academic_year: academicYear,
        term,
        week_start: weekStart,
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
      const rule = activeRuleTemplate?.config || conditions
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
      const rule = activeRuleTemplate?.config || conditions
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
    if (activeTab === 'schedule') void loadVersions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const updateConditions = (next: ScheduleRuleConfig) => {
    setConditions(next)
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
    if (!assignmentForm.teacher_id || !assignmentForm.subject_id || !assignmentForm.class_id) {
      message.warning('请选择教师、学科和班级')
      return
    }
    setSavingAssignment(true)
    try {
      await schedulingApi.saveAssignment({
        teacher_id: assignmentForm.teacher_id,
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
    setAssignmentForm({ weekly_periods: 4, room: '' })
    setAssignmentVisible(true)
  }

  const editAssignment = (item: TeachingAssignment) => {
    setEditingAssignment(item)
    setAssignmentModalTitle(`编辑任教关系 · ${item.subject_name || ''}`)
    setAssignmentForm({
      teacher_id: item.teacher_id,
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

  const assignmentColumns: TableProps<TeachingAssignment>['columns'] = [
    { title: '班级', dataIndex: 'class_name', key: 'class_name', width: 200, ellipsis: true },
    { title: '学科', dataIndex: 'subject_name', key: 'subject_name', width: 90, ellipsis: true },
    { title: '教师', dataIndex: 'teacher_name', key: 'teacher_name', width: 230, ellipsis: true },
    { title: '每周课时', dataIndex: 'weekly_periods', key: 'weekly_periods', width: 100, align: 'center' },
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
      <p className="zh-page-desc">先建立排课规则模板，再选择模板生成任教关系与日课表；所有模板保留历史版本可复用。</p>

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
        onChange={(key) => setActiveTab(key as 'rules' | 'assignments' | 'schedule')}
        items={[
          {
            key: 'rules',
            label: '建立规则',
            children: (
              <div className="st-rules">
                <TableCard>
                  <div className="zh-table-head">
                    <div className="zh-table-head-title">
                      <h2>排课规则模板</h2>
                      <p>配置每日节数、同科每日上限、教师跨班数、禁排时段与策略组合；模板可多条，生成课表时选一条即可。</p>
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
                        title: '每日节数',
                        width: 112,
                        render: (_, r) => (
                          <Tag>
                            {r.config.days} 天 × {r.config.periods_per_day} 节
                          </Tag>
                        ),
                      },
                      {
                        title: '同科每日',
                        dataIndex: ['config', 'max_same_subject_per_day'],
                        width: 108,
                        render: (v) => `≤ ${v} 节`,
                      },
                      {
                        title: '教师跨班',
                        dataIndex: ['config', 'max_classes_per_teacher'],
                        width: 112,
                        render: (v) => `≤ ${v} 个班`,
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
                          const dims = `班级每日≤${r.config.max_class_lessons_per_day} · 教师每日≤${r.config.max_teacher_lessons_per_day} · 教师每周≤${r.config.max_teacher_weekly_periods ?? 30}${r.config.pe_weekly_periods ? ` · 体育${r.config.pe_weekly_periods}节` : ''} · 禁排${r.config.forbidden_slots.length}时段`
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
                    <Button onClick={() => {
                      setAutoTeachingResult(undefined)
                      // 模版生成默认带上标准课时方案,避免空规则导致 10 科按默认 4 节爆班级容量
                      const entries = periodPlanEntries(BUILTIN_PERIOD_PLANS[0])
                      setAutoSubjectRules(entries)
                      setAutoSubjectTeacherLimits(entries.map((item) => ({ subject_id: item.subject_id, max_weekly_periods: autoMaxWeeklyPeriods })))
                      const pePeriods = conditions.pe_weekly_periods
                      if (pePeriods && peSubject) {
                        setAutoSubjectRules((current) => [...current.filter((item) => item.subject_id !== peSubject.id), { subject_id: peSubject.id, weekly_periods: pePeriods }])
                        setAutoSubjectTeacherLimits((current) => [...current.filter((item) => item.subject_id !== peSubject.id), { subject_id: peSubject.id, max_weekly_periods: autoMaxWeeklyPeriods }])
                      }
                      void loadScopeRules()
                      void loadAutoGrades().then(() => setAutoTeachingVisible(true))
                    }}>模版生成</Button>
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
              <section className="sk-surface">
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
                    <Button onClick={() => window.print()}>
                      <Icon name="printer" size={14} />
                      打印
                    </Button>
                  </div>
                </div>
                {loading ? (
                  <div className="sk-schedule-loading">
                    <EmptyState icon="calendar" title="课表加载中…" height={320} />
                  </div>
                ) : (
                  calendar.length ? (
                    <ScheduleGrid entries={calendar} dateMode weekStart={weekStart} onLessonContextMenu={openAdjustment} />
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
        ]}
      />

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
          <Form.Item label="班级" required>
            <Select
              value={assignmentForm.class_id}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, class_id: v }))}
              options={resources.classes.map(classOption)}
            />
          </Form.Item>
          <Form.Item label="学科" required>
            <Select
              value={assignmentForm.subject_id}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, subject_id: v }))}
              options={resources.subjects
                .filter((item) => !resources.teaching_track_subject_ids?.includes(item.id))
                .map((item) => ({ label: item.name, value: item.id }))}
            />
          </Form.Item>
          <Form.Item label="教师" required>
            <Select
              value={assignmentForm.teacher_id}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, teacher_id: v }))}
              options={resources.teachers.map((item) => ({ label: item.name, value: item.id }))}
            />
          </Form.Item>
          <Form.Item label="每周课时">
            <InputNumber
              value={assignmentForm.weekly_periods}
              onChange={(v) => setAssignmentForm((prev) => ({ ...prev, weekly_periods: v ?? 4 }))}
              min={1}
              max={20}
              style={{ width: '100%' }}
            />
          </Form.Item>
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

      <Modal
        title={`模版生成任教关系 · ${academicYear} · 第${term}学期`}
        open={autoTeachingVisible}
        onCancel={() => setAutoTeachingVisible(false)}
        width={960}
        footer={<Space>
          <Button onClick={() => void runAutoTeaching(false)} loading={autoTeachingLoading}>智能编排</Button>
          <Button
            onClick={() => void runAutoTeaching(true)}
            type="primary"
            loading={autoTeachingLoading}
            disabled={!autoTeachingResult || autoTeachingResult.skipped_count > 0 || autoTeachingResult.workload_summary.some((item) => !item.sufficient)}
          >
            确认生成
          </Button>
        </Space>}
      >
        <div className="sk-auto-teaching-options">
          <label>生成范围
            <Select
              mode="multiple"
              allowClear
              value={autoGradeIds}
              onChange={(value: number[]) => { setAutoGradeIds(value); setAutoTeachingResult(undefined) }}
              options={grades.map((item) => ({ label: item.name, value: item.id }))}
              placeholder="全部年级（不选 = 全校所有班级）"
              style={{ minWidth: 220 }}
            />
          </label>
          <label>课时方案
            <Select
              value={autoTeachingPlan}
              placeholder="一键填充课时规则"
              style={{ minWidth: 210 }}
              onChange={(name) => {
                const plan = allPeriodPlans.find((item) => item.name === name)
                if (plan) applyPeriodPlan(plan)
              }}
              options={allPeriodPlans.map((item) => ({
                label: `${item.name}（${Object.values(item.rules).reduce((sum, periods) => sum + periods, 0)} 节）`,
                value: item.name,
              }))}
            />
          </label>
          <Button size="small" onClick={saveCurrentPeriodPlan}>存为方案</Button>
          <Button shape="circle" type="primary" aria-label="添加课时规则" onClick={addAutoSubjectRule}>+</Button>
        </div>
        <Table
          rowKey="subject_id"
          size="small"
          pagination={false}
          dataSource={autoSubjectRules}
          columns={[
            {
              title: '学科',
              render: (_: unknown, record: { subject_id: number }) => (
                <Select
                  value={record.subject_id}
                  onChange={(value: number) => updateAutoRuleSubject(record.subject_id, value)}
                  showSearch
                  optionFilterProp="label"
                  placeholder="选择学科"
                  style={{ minWidth: 160 }}
                  options={resources.subjects
                    .filter((item) => !resources.teaching_track_subject_ids?.includes(item.id))
                    .filter((item) => item.id === record.subject_id || !autoSubjectRules.some((rule) => rule.subject_id === item.id))
                    .map((item) => ({ label: item.name, value: item.id }))}
                />
              ),
            },
            {
              title: '每周课时',
              render: (_: unknown, record: { subject_id: number; weekly_periods: number }) => (
                <InputNumber min={1} max={20} value={record.weekly_periods} onChange={(value) => updateAutoRulePeriods(record.subject_id, value ?? autoWeeklyPeriods)} />
              ),
            },
            {
              title: '教师周上限',
              render: (_: unknown, record: { subject_id: number }) => (
                <InputNumber min={1} max={60} value={autoSubjectTeacherLimits.find((item) => item.subject_id === record.subject_id)?.max_weekly_periods ?? autoMaxWeeklyPeriods} onChange={(value) => updateAutoRuleLimit(record.subject_id, value ?? autoMaxWeeklyPeriods)} />
              ),
            },
            { title: '操作', render: (_: unknown, record: { subject_id: number }) => <Button type="link" danger onClick={() => { setAutoSubjectRules((current) => current.filter((item) => item.subject_id !== record.subject_id)); setAutoSubjectTeacherLimits((current) => current.filter((item) => item.subject_id !== record.subject_id)) }}>删除</Button> },
          ]}
          locale={{ emptyText: '暂未添加课时规则，请先点击 + 添加规则' }}
        />
        <p className="zh-page-desc">可用「课时方案」一键填充学科课时规则，或点击 + 逐条添加并在表格中调整学科、每周课时与教师周上限，再点击“智能编排”。系统会结合学生人数、师资负荷与排课时间结构（{conditions.days} 天 × 每日 {conditions.periods_per_day} 节 · 同科每日≤{conditions.max_same_subject_per_day} · 班级每日≤{conditions.max_class_lessons_per_day} · 教师每日≤{conditions.max_teacher_lessons_per_day} · 教师每周≤{autoMaxWeeklyPeriods} · 禁排 {conditions.forbidden_slots.length} 时段）自动计算每周课时并匹配教师；未添加规则的学科默认每周 {autoWeeklyPeriods} 节、教师上限 {autoMaxWeeklyPeriods} 节。可在“排课条件”的负荷上限中调整教师每周上限。</p>
        {autoTeachingResult && (() => {
          const passed = autoTeachingResult.skipped_count === 0 && autoTeachingResult.workload_summary.every((item) => item.sufficient)
          const plan = autoTeachingResult.plan || []
          return <div className={`sk-auto-teaching-result ${passed ? 'is-passed' : 'is-failed'}`} role="status">
            <div className="sk-auto-teaching-head">
              <strong>{passed ? '校验通过' : '校验未通过'}</strong>
              <span>{passed ? `已匹配 ${autoTeachingResult.created_count} 条任教关系` : `仍有 ${autoTeachingResult.skipped_count} 条任教关系无法匹配`}</span>
            </div>
            {!passed && <>
              <small>请检查教师授课范围、每周课时上限和最多带班数。</small>
              <Button type="link" size="small" onClick={() => setAutoTeachingLogsVisible((visible) => !visible)}>
                {autoTeachingLogsVisible ? '收起日志' : '查看日志'}
              </Button>
            </>}
            <Table<AutoTeachingPlanRow>
              rowKey={(record) => `${record.class_id}-${record.subject_id}-${record.status}`}
              size="small"
              pagination={{
                pageSize: 10,
                showSizeChanger: false,
                showTotal: (total) => `共 ${total} 条任教关系`,
                hideOnSinglePage: true,
              }}
              dataSource={plan}
              locale={{ emptyText: '暂无编排结果' }}
              columns={[
                { title: '班级', dataIndex: 'class_name', render: (v: string, r) => v || `班级 ${r.class_id}` },
                { title: '学科', dataIndex: 'subject_name', render: (v: string, r) => v || `学科 ${r.subject_id}` },
                { title: '学生数', dataIndex: 'student_count', width: 80, render: (v?: number) => v != null ? `${v} 人` : '—' },
                { title: '每周课时', dataIndex: 'weekly_periods', width: 90, render: (v?: number, r?: { suggested_weekly_periods?: number }) => {
                    if (v != null) return `${v} 节`
                    if (r?.suggested_weekly_periods != null) return `建议 ${r.suggested_weekly_periods} 节`
                    return '—'
                  } },
                { title: '教师', dataIndex: 'teacher_name', render: (v: string, r) => v || (r.status === 'skipped' ? '—' : '') },
                { title: '状态', dataIndex: 'status', width: 110, render: (v: string) => v === 'success' ? <Tag color="green">匹配成功</Tag> : <Tag color="red">未匹配</Tag> },
                { title: '说明', dataIndex: 'reason', ellipsis: true, render: (v?: string) => v || '' },
              ]}
            />
          </div>
        })()}
      </Modal>

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
            <div className="sk-template-editor-head">
              <div>
                <h3>模板规则内容</h3>
                <p>包含：每日节数 / 同科每日上限 / 教师跨班数 / 禁排时段 / 策略组合等维度</p>
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
              <div><dt>上课日 / 每日节数</dt><dd>{ruleTemplateForm.config.days} 天 × {ruleTemplateForm.config.periods_per_day} 节</dd></div>
              <div><dt>班级每日节数上限</dt><dd>{ruleTemplateForm.config.max_class_lessons_per_day} 节</dd></div>
              <div><dt>教师每日节数上限</dt><dd>{ruleTemplateForm.config.max_teacher_lessons_per_day} 节</dd></div>
              <div><dt>教师每周节数上限</dt><dd>{ruleTemplateForm.config.max_teacher_weekly_periods ?? 30} 节</dd></div>
              <div><dt>体育课每周节数</dt><dd>{ruleTemplateForm.config.pe_weekly_periods ? `${ruleTemplateForm.config.pe_weekly_periods} 节` : '默认'}</dd></div>
              <div><dt>同科每日节数上限</dt><dd>{ruleTemplateForm.config.max_same_subject_per_day} 节</dd></div>
              <div><dt>教师跨班数上限</dt><dd>{ruleTemplateForm.config.max_classes_per_teacher} 个班</dd></div>
              <div><dt>避免教师连堂</dt><dd>{ruleTemplateForm.config.avoid_consecutive_teacher_lessons ? '是' : '否'}</dd></div>
              <div><dt>填满整周</dt><dd>{ruleTemplateForm.config.require_full_week ? '启用' : '不启用'}</dd></div>
              <div><dt>禁排时段</dt><dd>{ruleTemplateForm.config.forbidden_slots.length} 个</dd></div>
              <div><dt>启用策略</dt><dd>{ruleTemplateForm.config.strategy_codes.length} 项</dd></div>
            </dl>
          </div>
          <div className="sk-help">
            <strong>使用流程：</strong>先点「在规则设计器中编辑」设置维度并保存校验 → 再「同步当前规则到模板」→ 最后「保存规则」写入模板。
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
