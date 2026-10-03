import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { App, Button, Checkbox, DatePicker, Dropdown, Form, Input, InputNumber, Modal, Popconfirm, Progress, Select, Space, Switch, Table, Tabs, Tag, Tooltip } from 'antd'
import type { TableProps, MenuProps } from 'antd'
import dayjs from 'dayjs'
import { authApi, fileCenterApi, orgApi, schedulingApi } from '@/api'
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
import { setAssistantContext, clearAssistantContext } from '@/assistant/context'
import RuleGroupWorkbench, {
  ruleGroupScopeLabel,
  type RuleGroup,
} from './RuleGroupWorkbench'
import GenerationDiagnosisDrawer from './GenerationDiagnosisDrawer'
import GenerationWorkspace from './GenerationWorkspace'
import CourseHoursPanel from './course-hours'
import ScheduleVerifyWorkbench from './ScheduleVerifyWorkbench'
import SlotStructurePanel from './SlotStructurePanel'
import {
  BUILTIN_PERIOD_PLANS,
  DEFAULT_GRID_CONFIG,
  appendGenTrace,
  GEN_STEPS,
  MONDAY,
  NOW,
  PERIOD_PLANS_KEY,
  SCHOOL_YEAR,
  SUBJECT_ORDER,
  WEEKDAY_NAMES,
  buildGenerationPayload,
  buildRuleGridConfig,
  getConfiguredSlotOptions,
  localDateValue,
  normalizeGridConfig,
  parseGenerationDiagnosis,
  type GenerationDiagnosis,
  type GenTraceEvent,
} from './scheduling-model'
import useRuleTemplates from './use-rule-templates'
import './index.css'
import type {
  AssignmentForm,
  GenStage,
  ScheduleAdjustmentOption,
  SubstituteOption,
} from './scheduling-model'

export default function SchedulingView() {
  const { message } = App.useApp()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [genStage, setGenStage] = useState<GenStage>('idle')
  const [failedStageIndex, setFailedStageIndex] = useState(0)
  const [issues, setIssues] = useState<ScheduleValidationIssue[]>([])
  const [showAllIssues, setShowAllIssues] = useState(false)
  const [validation, setValidation] = useState<ScheduleValidationResult | null>(null)
  const [, setValidatedSignature] = useState('')
  const [validatingRules, setValidatingRules] = useState(false)
  const [genSummary, setGenSummary] = useState('')
  const [genPercent, setGenPercent] = useState(0)
  const [genElapsed, setGenElapsed] = useState(0)
  const [genSolutions, setGenSolutions] = useState(0)
  const [genDiagnosis, setGenDiagnosis] = useState<GenerationDiagnosis | null>(null)
  const [genTrace, setGenTrace] = useState<GenTraceEvent[]>([])
  const [generationFocus, setGenerationFocus] = useState<{
    groupId: string
    token: number
  } | null>(null)
  const [diagOpen, setDiagOpen] = useState(false)
  const [generationWorkspaceOpen, setGenerationWorkspaceOpen] = useState(false)
  const [ruleCatalogEpoch, setRuleCatalogEpoch] = useState(0)
  useEffect(() => {
    const refreshRules = () => setRuleCatalogEpoch((n) => n + 1)
    window.addEventListener('lc-assistant-rules-saved', refreshRules)
    return () => window.removeEventListener('lc-assistant-rules-saved', refreshRules)
  }, [])
  const [verifyVisible, setVerifyVisible] = useState(false)
  const lastGenerateRef = useRef<{ classIds?: number[]; ruleGroupId?: string }>({})
  const genWallClockRef = useRef<number | null>(null)

  // SSE 被代理缓冲时，至少让「已用时」按墙钟走，避免界面假死在 2s
  useEffect(() => {
    if (!generating) {
      genWallClockRef.current = null
      return
    }
    if (genWallClockRef.current == null) {
      genWallClockRef.current = Date.now()
    }
    const timer = window.setInterval(() => {
      const started = genWallClockRef.current
      if (started == null) return
      setGenElapsed((prev) => Math.max(prev, (Date.now() - started) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [generating])

  const [scheduleVersions, setScheduleVersions] = useState<ScheduleVersionSummary[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)

  const [activeTab, setActiveTab] = useState<'hours' | 'slots' | 'rules' | 'assignments' | 'schedule'>('slots')
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    const tab = searchParams.get('tab')
    if (tab === 'hours' || tab === 'slots' || tab === 'rules' || tab === 'assignments' || tab === 'schedule') {
      setActiveTab(tab)
      return
    }
    const next = new URLSearchParams(searchParams)
    next.set('tab', 'slots')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

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
  useEffect(() => {
    const raw = searchParams.get('grade')
    if (!raw || !resources.classes.length) return
    const gid = Number(raw)
    if (!Number.isFinite(gid)) return
    const first = resources.classes.find((item) => Number(item.grade_id) === gid)
    if (first) setSelectedClassId(first.id)
  }, [searchParams, resources.classes])
  const [assignKeyword, setAssignKeyword] = useState('')
  const [appliedAssignKeyword, setAppliedAssignKeyword] = useState('')
  const [assignPage, setAssignPage] = useState(1)
  const [assignPageSize, setAssignPageSize] = useState(10)
  const [academicYear, setAcademicYear] = useState(`${SCHOOL_YEAR}-${SCHOOL_YEAR + 1}`)
  const [term, setTerm] = useState(NOW.getMonth() >= 1 && NOW.getMonth() < 7 ? '2' : '1')
  const [weekStart] = useState<string>(localDateValue(MONDAY))
  const [gridConfigVisible, setGridConfigVisible] = useState(false)
  const [savingGridConfig, setSavingGridConfig] = useState(false)
  const [gridConfigured, setGridConfigured] = useState(false)
  const [gridConfig, setGridConfig] = useState<SchedulingGridConfig>(DEFAULT_GRID_CONFIG)

  // 弹窗
  const [assignmentVisible, setAssignmentVisible] = useState(false)
  const [editingAssignment, setEditingAssignment] = useState<TeachingAssignment>()
  const [assignmentModalTitle, setAssignmentModalTitle] = useState('新建任教关系')
  const [teacherVisible, setTeacherVisible] = useState(false)
  const [conditionVisible, setConditionVisible] = useState(false)
  const [generationRuleVisible, setGenerationRuleVisible] = useState(false)
  const [generateRuleOptions, setGenerateRuleOptions] = useState<RuleGroup[]>([])
  const [selectedGenerateRuleId, setSelectedGenerateRuleId] = useState<string>()
  useEffect(() => {
    setAssistantContext('schedule', { academic_year: academicYear, term, class_id: selectedClassId, class_name: resources.classes.find((c) => c.id === selectedClassId)?.name })
    return () => { clearAssistantContext('schedule'); clearAssistantContext('generation') }
  }, [academicYear, term, selectedClassId, resources.classes])
  const [adjustmentEntry, setAdjustmentEntry] = useState<ScheduleEntry>()
  const [adjustmentOptions, setAdjustmentOptions] = useState<ScheduleAdjustmentOption[]>([])
  const [adjustmentLoading, setAdjustmentLoading] = useState(false)
  const [movingSchedule, setMovingSchedule] = useState(false)
  const [substituteOptions, setSubstituteOptions] = useState<SubstituteOption[]>([])
  const [adjustmentTab, setAdjustmentTab] = useState<'move' | 'substitute'>('move')
  const [adjustConfirmOpen, setAdjustConfirmOpen] = useState(false)
  const [adjustPreview, setAdjustPreview] = useState<ScheduleAdjustmentOption | null>(null)
  const [adjustPreviewLoading, setAdjustPreviewLoading] = useState(false)
  const [acknowledgedChecks, setAcknowledgedChecks] = useState<Record<string, boolean>>({})
  const [exportModalOpen, setExportModalOpen] = useState(false)
  /** 导出目标：'all' = 全部班级，否则为班级 id */
  const [exportClassKey, setExportClassKey] = useState<number | 'all'>('all')
  const [exportSheets, setExportSheets] = useState<string[]>([
    'cover',
    'teacher_relation',
    'teacher_hours',
    'teacher_grid',
    'class_timetables',
  ])
  const [exportSubmitting, setExportSubmitting] = useState(false)
  const [exportDoneOpen, setExportDoneOpen] = useState(false)
  const [exportDoneInfo, setExportDoneInfo] = useState<{
    jobTypeLabel: string
    directionLabel: string
    scope: string
    fileName?: string
  } | null>(null)
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
  const [teacherForm, setTeacherForm] = useState({ name: '', phone: '', password: '' })
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

  const configuredSlotOptions = useMemo(() => getConfiguredSlotOptions(gridConfig), [gridConfig])

  const ruleTemplatesState = useRuleTemplates({
    academicYear,
    term,
    onConfigApplied: (config) => {
      setConditions(config)
      setValidation(null)
      setValidatedSignature('')
    },
    onScopeRulesApplied: setScopeRules,
  })
  const {
    ruleTemplates,
    defaultRuleTemplateId,
    setDefaultRuleTemplateId,
    ruleTemplateModalOpen,
    setRuleTemplateModalOpen,
    editingRuleTemplateId,
    ruleTemplateForm,
    setRuleTemplateForm,
    activeRuleTemplate,
    openRuleTemplateModal,
    saveRuleTemplate,
    deleteRuleTemplate,
    toggleRuleTemplate,
  } = ruleTemplatesState

  const selectedClassName = useMemo(
    () => resources.classes.find((item) => item.id === selectedClassId)?.name || '全部班级',
    [resources.classes, selectedClassId],
  )
  const gradeScheduleLabel = useMemo(() => {
    const sample = resources.classes[0]?.name || ''
    const matched = sample.match(/^(高[一二三]|初[一二三])/)
    return matched ? `${matched[1]}年级` : '本年级'
  }, [resources.classes])
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
    setSelectedClassId(undefined)
    setAssignPage(1)
  }

  const genStepIndex = useMemo(() => {
    const index = GEN_STEPS.findIndex((item) => item.code === genStage)
    return index >= 0 ? index : failedStageIndex
  }, [genStage, failedStageIndex])

  const ruleGridConfig = (config: ScheduleRuleConfig) => buildRuleGridConfig(config, gridConfig)
  const generationPayload = (config: ScheduleRuleConfig = conditions) => (
    buildGenerationPayload(config, gridConfig, academicYear, term)
  )

  const formatGenerationError = (error: unknown) => {
    const fallback = error instanceof Error ? error.message : '生成课表失败'
    const diagnosis = parseGenerationDiagnosis(error)
    if (diagnosis?.summary) return diagnosis.summary
    try {
      const detail = JSON.parse(fallback) as {
        message?: unknown
        rule_validation?: {
          results?: Array<{
            priority: string
            status: string
            title: string
            message: string
          }>
        }
      }
      const failures = detail.rule_validation?.results?.filter(
        (item) => item.priority === 'hard' && ['fail', 'unresolved', 'not_run'].includes(item.status),
      ) || []
      if (failures.length) {
        const names = failures.slice(0, 3).map((item) => `${item.title}（${item.message}）`).join('；')
        const suffix = failures.length > 3 ? `；另有 ${failures.length - 3} 条` : ''
        return `${typeof detail.message === 'string' ? detail.message : '规则校验未通过'}：${names}${suffix}`
      }
      if (typeof detail.message === 'string') return detail.message
    } catch {
      // 普通 API 错误不需要额外解析。
    }
    return fallback
  }

  const payloadSignature = () => JSON.stringify(generationPayload())

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
    const [data, strategyOptions, academicSettings, gradeList] = await Promise.all([
      schedulingApi.resources(),
      schedulingApi.strategies(),
      authApi.academicYears(),
      orgApi.grades().catch(() => [] as Grade[]),
    ])
    setResources(data)
    setStrategies(strategyOptions)
    setGrades(gradeList)
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

  const loadTable = async (classIdOverride?: number) => {
    const classIds = resources.classes.map((item) => item.id)
    if (!classIds.length) {
      setCalendar([])
      return
    }
    const primaryId = classIdOverride ?? selectedClassId ?? classIds[0]
    if (!generating) setLoading(true)
    try {
      // 先拉当前班，避免 N 个并行 weekly 任一失败就整页 Network Error
      const primary = await schedulingApi.weekly({
        class_id: primaryId,
        academic_year: academicYear,
        term,
      })
      setCalendar(primary)
      if (!generating) setLoading(false)

      const rest = classIds.filter((id) => id !== primaryId)
      if (!rest.length) return
      const settled = await Promise.allSettled(
        rest.map((classId) =>
          schedulingApi.weekly({
            class_id: classId,
            academic_year: academicYear,
            term,
          }),
        ),
      )
      const extras = settled.flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
      setCalendar((prev) => {
        const keep = prev.filter((entry) => entry.class_id === primaryId)
        return [...keep, ...extras]
      })
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
    setAdjustConfirmOpen(false)
    setAdjustPreview(null)
    setAcknowledgedChecks({})
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

  const openAdjustConfirm = async (option: ScheduleAdjustmentOption) => {
    if (!adjustmentEntry || option.selectable === false) return
    setAdjustPreviewLoading(true)
    setAdjustConfirmOpen(true)
    setAdjustPreview(null)
    setAcknowledgedChecks({})
    try {
      const rule = ruleGridConfig(activeRuleTemplate?.config || conditions)
      const preview = await schedulingApi.previewAdjustment({
        schedule_id: adjustmentEntry.id,
        target_weekday: option.weekday,
        target_period: option.period,
        target_week_parity: option.week_parity,
        academic_year: academicYear,
        term,
        days: rule.days,
        periods_per_day: rule.periods_per_day,
      })
      setAdjustPreview(preview)
      // 系统判定「通过」的默认打勾；「未通过」仍需用户手动点成 √
      setAcknowledgedChecks(
        Object.fromEntries(
          (preview.checks || []).map((item) => [item.key, Boolean(item.passed)]),
        ),
      )
    } catch (error) {
      setAdjustConfirmOpen(false)
      message.error(error instanceof Error ? error.message : '检查项加载失败')
    } finally {
      setAdjustPreviewLoading(false)
    }
  }

  const allChecksAcknowledged = Boolean(
    adjustPreview
    && (
      !(adjustPreview.checks?.length)
        ? true
        : adjustPreview.checks.every((item) => acknowledgedChecks[item.key])
    ),
  )

  const confirmMoveEntry = async () => {
    if (!adjustmentEntry || !adjustPreview || !allChecksAcknowledged) return
    setMovingSchedule(true)
    try {
      const rule = ruleGridConfig(activeRuleTemplate?.config || conditions)
      const result = await schedulingApi.moveSchedule({
        schedule_id: adjustmentEntry.id,
        target_weekday: adjustPreview.weekday,
        target_period: adjustPreview.period,
        target_week_parity: adjustPreview.week_parity,
        academic_year: academicYear,
        term,
        days: rule.days,
        periods_per_day: rule.periods_per_day,
        force: true,
      })
      setAdjustConfirmOpen(false)
      setAdjustPreview(null)
      setAdjustmentEntry(undefined)
      await loadTable()
      const swapped = result.mode === 'swap'
      message.success(swapped ? '对调成功' : '调课成功')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '调课失败')
    } finally {
      setMovingSchedule(false)
    }
  }

  const saveGridConfig = async () => {
    setSavingGridConfig(true)
    try {
      const payload = normalizeGridConfig(gridConfig)
      const saved = await schedulingApi.saveGridConfig({ ...payload, academic_year: academicYear, term })
      setGridConfig(normalizeGridConfig({ ...saved, configured: true }))
      setGridConfigured(true)
      setGridConfigVisible(false)
      message.success('课位结构已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课位结构保存失败')
    } finally {
      setSavingGridConfig(false)
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
    void schedulingApi.gridConfig({ academic_year: academicYear, term })
      .then((config) => {
        setGridConfig(normalizeGridConfig(config))
        setGridConfigured(Boolean(config.configured))
        if (!config.configured) setActiveTab('slots')
      })
      .catch(() => undefined)
  }, [academicYear, term])

  useEffect(() => {
    if (activeTab !== 'schedule') return
    if (selectedClassId === undefined && resources.classes[0]?.id != null) {
      setSelectedClassId(resources.classes[0].id)
    }
    void loadVersions()
    void loadTable()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, academicYear, term, weekStart, resources.classes.length])

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
        ...normalizeGridConfig(ruleGridConfig(conditions)),
        academic_year: academicYear,
        term,
      })
      setGridConfig(normalizeGridConfig(savedGrid))
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

  const classesForGrade = (gradeId: number | null | undefined) => {
    if (gradeId == null) return []
    const target = Number(gradeId)
    if (!Number.isFinite(target)) return []
    return resources.classes
      .filter((item) => Number(item.grade_id) === target)
      .map((item) => item.id)
  }

  const openDiagnosisDrawer = (diagnosis: GenerationDiagnosis | null = genDiagnosis) => {
    if (diagnosis) setGenDiagnosis(diagnosis)
    setDiagOpen(true)
  }

  const openRuleWorkbenchForGroup = (groupId?: string) => {
    const id =
      groupId ||
      genDiagnosis?.rule_group_id ||
      lastGenerateRef.current.ruleGroupId
    setDiagOpen(false)
    setActiveTab('rules')
    if (id) setGenerationFocus({ groupId: id, token: Date.now() })
  }

  const followGenerateJob = async (jobId: string, signal?: AbortSignal) => {
    let streamedDiagnosis: GenerationDiagnosis | null = null
    try {
      type GenerateJobResult = {
        created: number
        class_count: number
        unplaced?: Array<{ assignment_id: number; count: number }>
      }
      let result: GenerateJobResult | null = null
      let jobError: unknown = null
      await schedulingApi.streamGenerateJob(jobId, (event) => {
        if (event.stage === 'validating' || event.stage === 'generating' || event.stage === 'refreshing' || event.stage === 'done') {
          setGenStage(event.stage)
          if (event.stage === 'validating') setFailedStageIndex(0)
          if (event.stage === 'generating') setFailedStageIndex(1)
          if (event.stage === 'refreshing') setFailedStageIndex(2)
          if (event.stage === 'done') setFailedStageIndex(3)
        }
        if (event.message) setGenSummary(event.message)
        if (typeof event.percent === 'number') setGenPercent(Math.max(0, Math.min(100, event.percent)))
        if (typeof event.elapsed === 'number') {
          setGenElapsed((prev) => Math.max(prev, event.elapsed as number))
        }
        if (typeof event.solutions === 'number') setGenSolutions(event.solutions)
        if (event.type === 'progress' || event.type === 'error' || event.message) {
          setGenTrace((prev) =>
            appendGenTrace(prev, {
              stage: event.stage,
              phase: event.phase,
              message: event.message,
              percent: event.percent,
              elapsed: event.elapsed,
              solutions: event.solutions,
            }),
          )
        }
        if (event.type === 'done' && event.result) {
          result = event.result
          setGenPercent(100)
        }
        if (event.type === 'error') {
          jobError =
            event.detail && typeof event.detail === 'object'
              ? event.detail
              : { message: event.message || '生成失败' }
          streamedDiagnosis = parseGenerationDiagnosis(jobError)
          if (streamedDiagnosis) setGenDiagnosis(streamedDiagnosis)
        }
      }, signal)
      if (jobError) {
        throw new Error(
          typeof jobError === 'string'
            ? jobError
            : JSON.stringify(jobError),
        )
      }
      if (!result) throw new Error('生成任务未返回结果')
      const generated = result as {
        created: number
        class_count: number
        unplaced?: Array<{ assignment_id: number; count: number }>
      }
      setGenStage('refreshing')
      setFailedStageIndex(2)
      setGenSummary(`已生成 ${generated.created} 节课，正在刷新周课表与日期课表`)
      await loadTable()
      setGenStage('done')
      setFailedStageIndex(3)
      setGenSummary(`已完成 ${generated.class_count} 个班、${generated.created} 节课`)
      const unplaced = generated.unplaced?.reduce((sum: number, item: { count: number }) => sum + item.count, 0) ?? 0
      if (unplaced) message.warning(`已生成 ${generated.created} 节，另有 ${unplaced} 节未能排入`)
      else message.success(`已为 ${generated.class_count} 个班生成 ${generated.created} 节课程`)
      void loadVersions()
      setDiagOpen(false)
    } catch (e) {
      if (signal?.aborted) return
      setGenStage('error')
      const diagnosis = streamedDiagnosis || parseGenerationDiagnosis(e)
      if (diagnosis) setGenDiagnosis(diagnosis)
      const detail = formatGenerationError(e)
      setGenSummary(detail)
      message.error(detail)
      openDiagnosisDrawer(diagnosis)
    } finally {
      setGenerating(false)
    }
  }

  const generateAll = async (classIds?: number[], ruleGroupId?: string) => {
    const generationConfig = activeRuleTemplate?.config || conditions
    lastGenerateRef.current = { classIds, ruleGroupId }
    genWallClockRef.current = Date.now()
    setGenerating(true)
    setGenStage('validating')
    setFailedStageIndex(0)
    setIssues([])
    setGenDiagnosis(null)
    setGenTrace([])
    setGenPercent(2)
    setGenElapsed(0)
    setGenSolutions(0)
    setGenSummary('已提交生成任务，等待进度…')
    setGenerationWorkspaceOpen(true)
    setDiagOpen(true)
    try {
      const payload = {
        ...generationPayload(generationConfig),
        ...(classIds?.length ? { class_ids: classIds } : {}),
        ...(ruleGroupId ? { rule_group_id: ruleGroupId } : {}),
      }
      const { job_id, resumed } = await schedulingApi.startGenerateJob(payload)
      setAssistantContext('generation', { job_id })
      if (resumed) setGenSummary('发现本学期已有排课任务，正在恢复进度…')
      await followGenerateJob(job_id)
    } catch (e) {
      setGenerating(false)
      setGenStage('error')
      const detail = formatGenerationError(e)
      setGenSummary(detail)
      message.error(detail)
      openDiagnosisDrawer()
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    void schedulingApi.activeGenerateJob({ academic_year: academicYear, term })
      .then(async (job) => {
        if (!job || controller.signal.aborted) return
        genWallClockRef.current = Date.parse(job.created_at) || Date.now()
        setGenerating(true)
        setGenStage(
          job.stage === 'generating' || job.stage === 'refreshing'
            ? job.stage
            : 'validating',
        )
        setFailedStageIndex(job.stage === 'refreshing' ? 2 : job.stage === 'generating' ? 1 : 0)
        setGenPercent(Math.max(0, Math.min(100, job.percent || 2)))
        setGenSummary(`正在恢复排课任务：${job.message}`)
        setGenTrace([])
        setDiagOpen(true)
        setAssistantContext('generation', { job_id: job.job_id })
        await followGenerateJob(job.job_id, controller.signal)
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          console.warn('恢复排课任务失败', error)
        }
      })
    return () => controller.abort()
    // 当前学年学期变化时重新寻找该范围内的活动任务。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [academicYear, term])

  const openVerifyWorkbench = () => {
    if (!calendar.length) {
      message.warning('请先生成课表后再做反向校验')
      return
    }
    setVerifyVisible(true)
  }

  const openGenerationRulePreview = async () => {
    try {
      const gradeList = grades.length ? grades : await orgApi.grades().catch(() => [] as Grade[])
      if (!grades.length && gradeList.length) setGrades(gradeList)
      const catalog = await schedulingApi.ruleGroups({ academic_year: academicYear, term })
      const options: RuleGroup[] = (catalog.groups || []).map((item) => {
        const grade_id = item.grade_id != null ? Number(item.grade_id) : null
        return {
          id: item.id,
          name: item.name,
          grade_id,
          scope: ruleGroupScopeLabel(
            { grade_id, scope: '' },
            gradeList,
            resources.classes,
          ),
          term: `${item.academic_year} · 第${item.term}学期`,
          rules: [],
        }
      })
      if (!options.length) {
        message.warning('请先在「建立规则」中新增综合规则（选择适用年级）')
        return
      }
      setGenerateRuleOptions(options)
      setSelectedGenerateRuleId(catalog.active_id || options[0]?.id)
      setGenerationRuleVisible(true)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载综合规则失败，请检查后端服务')
    }
  }

  const confirmGenerateByRule = async () => {
    const group = generateRuleOptions.find((item) => item.id === selectedGenerateRuleId)
    if (!group) {
      message.warning('请选择要生成的综合规则（年级）')
      return
    }
    const classIds = classesForGrade(group.grade_id)
    if (!classIds.length) {
      message.warning(`「${ruleGroupScopeLabel(group, grades, resources.classes)}」下没有可排课班级`)
      return
    }
    setGenerationRuleVisible(false)
    void generateAll(classIds, group.id)
  }

  const loadVersions = async () => {
    try {
      setVersionsLoading(true)
      const list = await schedulingApi.listVersions()
      setScheduleVersions(list || [])
    } catch (e) {
      setScheduleVersions([])
      // 版本列表失败不阻断课表，但给出可读提示（避免误以为整页挂了）
      const detail = e instanceof Error ? e.message : '课表版本加载失败'
      if (detail === 'Network Error') {
        message.warning('课表版本暂时无法连接后端，请确认服务已启动后刷新')
      }
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
      setTeacherForm({ name: '', phone: '', password: '' })
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
      <GenerationWorkspace
        open={generationWorkspaceOpen}
        generating={generating}
        stage={genStage}
        percent={genPercent}
        elapsed={genElapsed}
        solutions={genSolutions}
        summary={genSummary}
        trace={genTrace}
        assignments={resources.assignments.filter((item) => item.academic_year === academicYear && item.term === term && (selectedClassId === undefined || item.class_id === selectedClassId))}
        subjects={resources.subjects.map((item) => ({ id: item.id, name: item.name }))}
        calendar={calendar.filter((item) => selectedClassId === undefined || item.class_id === selectedClassId)}
        gridConfig={gridConfig}
        academicYear={academicYear}
        term={term}
        classes={resources.classes.map((item) => ({ id: item.id, name: item.name }))}
        selectedClassId={selectedClassId}
        selectedClassName={selectedClassName}
        onClassChange={(classId) => {
          setSelectedClassId(classId)
          if (!generating) void loadTable(classId)
        }}
        onClose={() => setGenerationWorkspaceOpen(false)}
      />
      <PageHeader
        title="排课管理"
        extra={
          activeTab === 'assignments' ? (
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
              {(generating || genPercent > 0) && (
                <div className="sk-status-meta">
                  <span>进度 {Math.round(genPercent)}%</span>
                  <span>已用时 {Math.max(0, Math.floor(genElapsed))}s</span>
                  {genSolutions > 0 ? <span>可行解 {genSolutions} 个</span> : null}
                </div>
              )}
            </div>
            {(generating || genStage === 'done' || genPercent > 0) && (
              <Button type="primary" size="small" onClick={() => setGenerationWorkspaceOpen(true)}>
                打开数字孪生
              </Button>
            )}
            {!generating && (
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setGenStage('idle')
                  setGenDiagnosis(null)
                  setGenTrace([])
                }}
              >
                收起
              </Button>
            )}
            {(generating || genStage === 'error') && (
              <Button type="link" size="small" onClick={() => setDiagOpen(true)}>
                排课诊断
              </Button>
            )}
          </div>
          {(generating || genStage === 'done' || genPercent > 0) && (
            <Progress
              className="sk-status-progress"
              percent={Math.round(genPercent)}
              status={
                genStage === 'error' || genStage === 'blocked'
                  ? 'exception'
                  : genStage === 'done'
                    ? 'success'
                    : 'active'
              }
              showInfo
              strokeColor={genStage === 'done' ? undefined : { from: '#4c6fff', to: '#7aa2ff' }}
            />
          )}
          <ol className="sk-track" aria-label="生成进度">
            {GEN_STEPS.map((step, index) => {
              const isDone = genStage === 'done' || genStepIndex > index
              const isActive =
                generating &&
                genStepIndex === index &&
                genStage !== 'blocked' &&
                genStage !== 'error'
              const isFailed =
                (genStage === 'blocked' || genStage === 'error') &&
                genStepIndex === index
              return (
                <li
                  key={step.code}
                  className={[
                    'sk-step',
                    isActive ? 'active' : '',
                    isDone ? 'done' : '',
                    isFailed ? 'failed' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  <div className="sk-step-node">
                    <i aria-hidden="true">{isDone ? '✓' : ''}</i>
                    {index < GEN_STEPS.length - 1 ? (
                      <b
                        className={[
                          'sk-step-connector',
                          isDone ? 'done' : '',
                          isActive ? 'active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        aria-hidden="true"
                      />
                    ) : null}
                  </div>
                  <span>{step.label}</span>
                </li>
              )
            })}
          </ol>
          {genStage === 'error' && (
            <div className="sk-diagnosis">
              <p className="sk-diagnosis-hint" style={{ marginTop: 0 }}>
                {genDiagnosis?.stuck_label || '生成未完成。'}
                详细过程与优化建议在右侧「排课诊断」中查看，改规则请进独立的规则工作台。
              </p>
              <Button
                type="primary"
                size="small"
                onClick={() => openDiagnosisDrawer(genDiagnosis)}
              >
                打开排课诊断
              </Button>
            </div>
          )}
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

      <Tabs
        className="sk-tabs"
        activeKey={activeTab}
        onChange={(key) => {
          const tab = key as 'hours' | 'slots' | 'rules' | 'assignments' | 'schedule'
          setActiveTab(tab)
          const next = new URLSearchParams(searchParams)
          next.set('tab', tab)
          setSearchParams(next, { replace: true })
        }}
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
                onClassChange={setSelectedClassId}
                classOptions={resources.classes.map(classOption)}
              />
            ),
          },
          {
            key: 'slots',
            label: '课位结构',
            children: (
              <SlotStructurePanel
                config={gridConfig}
                academicYear={academicYear}
                term={term}
                saving={savingGridConfig}
                onChange={setGridConfig}
                onSave={() => void saveGridConfig()}
              />
            ),
          },
          {
            key: 'rules',
            label: '建立规则',
            disabled: !gridConfigured,
            children: (
              <div className="st-rules">
                <RuleGroupWorkbench
                  slotOptions={configuredSlotOptions}
                  academicYear={academicYear}
                  term={term}
                  resources={resources}
                  grades={grades}
                  openGroupRequest={generationFocus}
                  catalogEpoch={ruleCatalogEpoch}
                />
                <div className="st-rules-legacy">
                <TableCard>
                  <div className="zh-table-head">
                    <div className="zh-table-head-title">
                      <h2>排课规则模板</h2>
                      <p>课时在“课时管理”按班级维护，课位在“课位结构”统一维护；这里仅配置负载上限、教师约束、禁排时段与策略组合。</p>
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
                    <Select
                      allowClear
                      value={selectedClassId}
                      onChange={(next) => {
                        setSelectedClassId(next)
                        setAssignPage(1)
                      }}
                      placeholder="全部班级"
                      style={{ width: 200 }}
                      popupMatchSelectWidth={280}
                      options={resources.classes.map(classOption)}
                    />
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
            label: '课表',
            disabled: !gridConfigured,
            children: (
              <div className="sk-schedule-workspace">
              <section className="sk-surface sk-schedule-surface">
                <div className="sk-surface-head">
                  <div>
                    <div className="sk-surface-head-row">
                      <span className="sk-class-pill">{gradeScheduleLabel}</span>
                      <Tag className="sk-schedule-term-tag">{academicYear} 学年 · 第 {term} 学期</Tag>
                      <Tag className="sk-schedule-count-tag" style={{ whiteSpace: 'nowrap' }}>
                        {resources.classes.length} 个班
                      </Tag>
                    </div>
                    <h2>
                      {selectedClassName === '全部班级'
                        ? `${gradeScheduleLabel} · 年级日课表`
                        : `${selectedClassName} · 日课表`}
                    </h2>
                  </div>
                  <div className="sk-calendar-actions">
                    <Select
                      showSearch
                      optionFilterProp="label"
                      value={selectedClassId}
                      onChange={setSelectedClassId}
                      placeholder="选择班级"
                      className="sk-schedule-class-select"
                      style={{ width: 200 }}
                      popupMatchSelectWidth={260}
                      options={resources.classes.map(classOption)}
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
                          <span className="sk-version-count" style={{ marginLeft: 4, fontSize: 12 }}>（{scheduleVersions.length}）</span>
                        ) : null}
                      </Button>
                    </Dropdown>
                    <Button
                      type="primary"
                      loading={generating}
                      disabled={generating || !gridConfigured}
                      title={!gridConfigured ? '请先在“课位结构”中生成并保存课位结构' : undefined}
                      icon={!generating ? <Icon name="sparkles" size={14} /> : undefined}
                      onClick={openGenerationRulePreview}
                    >
                      {generating ? '正在生成' : '生成课表'}
                    </Button>
                    <Button
                      disabled={generating || calendar.length === 0}
                      title={
                        calendar.length === 0
                          ? '请先生成课表后再做反向校验'
                          : '打开工作台：选择综合规则后逐条校验课表'
                      }
                      onClick={openVerifyWorkbench}
                    >
                      结果反向校验
                    </Button>
                    <Button onClick={() => window.print()}>
                      <Icon name="printer" size={14} />
                      打印
                    </Button>
                    <Button
                      disabled={generating}
                      title="选择班级或全部后导出课表"
                      onClick={() => {
                        if (!resources.classes.length) {
                          message.warning('暂无班级可导出')
                          return
                        }
                        if (calendar.length === 0) {
                          message.warning('请先生成课表后再导出')
                          return
                        }
                        setExportClassKey(selectedClassId ?? 'all')
                        setExportSheets([
                          'cover',
                          'teacher_relation',
                          'teacher_hours',
                          'teacher_grid',
                          'class_timetables',
                        ])
                        setExportModalOpen(true)
                      }}
                    >
                      导出完整包
                    </Button>
                  </div>
                </div>
                <div className="sk-schedule-overview">
                  <div className="sk-schedule-overview-copy">
                    <span className="sk-schedule-overview-label">WEEKLY RHYTHM</span>
                    <strong>班级课程节奏</strong>
                    <span>生成按年级整批排课；这里下拉切换班级查看课表。</span>
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
                ) : (() => {
                  const viewClassId = selectedClassId ?? resources.classes[0]?.id
                  const entries = viewClassId
                    ? calendar.filter((item) => item.class_id === viewClassId)
                    : []
                  if (!viewClassId) {
                    return (
                      <EmptyState
                        icon="calendar"
                        title="暂无班级"
                        desc="请先在组织架构中配置班级。"
                        height={260}
                      />
                    )
                  }
                  if (!calendar.length) {
                    return (
                      <EmptyState
                        icon="calendar"
                        title={`${gradeScheduleLabel}还没有课表`}
                        desc="点击「生成课表」按综合规则为年级一次性排课。"
                        height={260}
                      />
                    )
                  }
                  if (!entries.length) {
                    return (
                      <EmptyState
                        icon="calendar"
                        title={`${selectedClassName}还没有课表`}
                        desc="该班尚未排入课程，可切换其他班级查看，或重新生成课表。"
                        height={260}
                      />
                    )
                  }
                  return (
                    <ScheduleGrid
                      entries={entries}
                      periods={gridConfig.periods_per_day}
                      days={gridConfig.days}
                      dailyPeriods={gridConfig.daily_periods}
                      showEvening
                      eveningStartPeriod={gridConfig.evening_start_period}
                      dateMode
                      weekStart={weekStart}
                      onLessonContextMenu={openAdjustment}
                    />
                  )
                })()}
              </section>
              </div>
            ),
          },
        ].sort((left, right) => {
          const order = ['hours', 'slots', 'assignments', 'rules', 'schedule']
          return order.indexOf(left.key) - order.indexOf(right.key)
        })}
      />

      <Modal title="课位结构设置" open={gridConfigVisible} onCancel={() => setGridConfigVisible(false)} onOk={() => void saveGridConfig()} width={760}>
        <Form layout="vertical">
          <p style={{ color: '#667085', marginTop: 0 }}>逐日设置正式课节数。未启用的日期填 0；自动排课会把超过当日节数的时段视为禁排。</p>
          <div className="sk-weekday-period-grid">
            {WEEKDAY_NAMES.map((name, index) => (
              <div key={name} className="sk-weekday-period-cell">
                <strong>{name}</strong>
                <InputNumber min={0} max={12} value={gridConfig.daily_periods[index]} addonAfter="节" onChange={(v) => setGridConfig((current) => {
                  const dailyPeriods = [...current.daily_periods]
                  dailyPeriods[index] = v ?? 0
                  return normalizeGridConfig({ ...current, daily_periods: dailyPeriods })
                })} />
              </div>
            ))}
          </div>
          <Space size="large">
            <Form.Item label="启用晚自习"><Switch checked={gridConfig.enable_evening} onChange={(v) => setGridConfig((x) => normalizeGridConfig({
              ...x,
              enable_evening: v,
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
                  return normalizeGridConfig({ ...current, [field]: profile })
                })} />)}
                <strong>{gridConfig[field].reduce((sum, count) => sum + count, 0)} 节</strong>
              </div>)}
            </div>
          </Form.Item>}
          {gridConfig.enable_evening && <div className="sk-grid-help sk-evening-business-note">
            晚自习每天只有 1 节。请在“课时管理”中填写晚课 0、0.5 或 1：1 为单双周同一科目不可拆开；0.5 再选择单周或双周，并与另一门 0.5 对课。各班晚课额度应排满一周 6 节，晚自习不排自主学习。
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
              <span>课时统一来自“课时管理”，课位统一来自“课位结构”；这里集中维护排课约束。</span>
            </div>
            <div className="sk-template-editor-head">
              <div>
                <h3>模板规则内容</h3>
                <p>模板只配置负载、完整度、教师约束、禁排与策略；科目课时和课位结构分别由“课时管理”“课位结构”维护。</p>
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
            <strong>使用流程：</strong>先在「课位结构」维护具体课位，再点「在规则设计器中编辑」设置约束并校验 → 「同步当前规则到模板」→ 「保存规则」。
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

      <Modal
        title="生成年级课表"
        open={generationRuleVisible}
        onCancel={() => setGenerationRuleVisible(false)}
        onOk={() => void confirmGenerateByRule()}
        okText="开始生成"
        cancelText="取消"
        confirmLoading={generating}
        destroyOnClose
        width={520}
      >
        <div className="sk-generate-rule-form">
          <p>
            选择一条综合规则即可确定生成年级。规则已关联高一/高二等组织范围，将为该年级全部班级一次性排课。
          </p>
          <label>
            <span>综合规则 / 年级</span>
            <Select
              style={{ width: '100%' }}
              value={selectedGenerateRuleId}
              placeholder="请选择综合规则"
              options={generateRuleOptions.map((item) => ({
                value: item.id,
                label: `${item.name}（${ruleGroupScopeLabel(item, grades, resources.classes)}）`,
              }))}
              onChange={setSelectedGenerateRuleId}
            />
          </label>
          {selectedGenerateRuleId ? (
            <small>
              {(() => {
                const group = generateRuleOptions.find((item) => item.id === selectedGenerateRuleId)
                const ids = classesForGrade(group?.grade_id)
                const names = resources.classes
                  .filter((item) => ids.includes(item.id))
                  .map((item) => item.name)
                if (!ids.length) return '未匹配到班级，请确认综合规则已关联组织年级'
                const preview = names.slice(0, 4).join('、')
                const more = names.length > 4 ? ` 等 ${names.length} 个班` : `，共 ${names.length} 个班`
                return `将生成：${preview}${more}`
              })()}
            </small>
          ) : null}
        </div>
      </Modal>

      <GenerationDiagnosisDrawer
        open={diagOpen}
        onClose={() => setDiagOpen(false)}
        generation={{
          generating,
          stage: genStage,
          percent: genPercent,
          elapsed: genElapsed,
          solutions: genSolutions,
          summary: genSummary,
          trace: genTrace,
          diagnosis: genDiagnosis,
          groupId:
            genDiagnosis?.rule_group_id || lastGenerateRef.current.ruleGroupId,
        }}
        academicYear={academicYear}
        term={term}
        onRetryGenerate={() => {
          const { classIds, ruleGroupId } = lastGenerateRef.current
          void generateAll(classIds, ruleGroupId)
        }}
        onGoHours={() => {
          setDiagOpen(false)
          setActiveTab('hours')
        }}
        onOpenRules={(groupId) => {
          setDiagOpen(false)
          openRuleWorkbenchForGroup(groupId)
        }}
        onSuggestionApplied={() => setRuleCatalogEpoch((n) => n + 1)}
      />

      <ScheduleVerifyWorkbench
        open={verifyVisible}
        onClose={() => setVerifyVisible(false)}
        academicYear={academicYear}
        term={term}
        classId={selectedClassId ?? resources.classes[0]?.id}
        grades={grades}
        classes={resources.classes}
      />

      <Modal
        title="导出排课完整包"
        open={exportModalOpen}
        onCancel={() => !exportSubmitting && setExportModalOpen(false)}
        okText="导出"
        cancelText="取消"
        confirmLoading={exportSubmitting}
        centered
        width={460}
        destroyOnClose
        onOk={async () => {
          if (!exportSheets.length) {
            message.warning('请至少勾选一种工作表')
            return Promise.reject()
          }
          setExportSubmitting(true)
          try {
            const classIds = exportClassKey === 'all' ? null : [exportClassKey]
            const scopeLabel = exportClassKey === 'all'
              ? '全部班级'
              : (resources.classes.find((item) => item.id === exportClassKey)?.name || '所选班级')
            const job = await fileCenterApi.exportTimetable({
              academic_year: academicYear,
              term,
              class_ids: classIds,
              periods_per_day: gridConfig.periods_per_day,
              evening_start_period: gridConfig.evening_start_period,
              sheets: exportSheets,
            })
            setExportModalOpen(false)
            setExportDoneInfo({
              jobTypeLabel: job.job_type_label || '导出排课完整包',
              directionLabel: '导出',
              scope: job.scope || scopeLabel,
              fileName: job.file_name || undefined,
            })
            setExportDoneOpen(true)
          } catch (error) {
            message.error(error instanceof Error ? error.message : '创建导出任务失败')
            return Promise.reject()
          } finally {
            setExportSubmitting(false)
          }
        }}
      >
        <p className="sk-adjustment-hint" style={{ marginBottom: 12 }}>
          先选班级范围，再勾选要打包的工作表，最后点「导出」。
        </p>
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 6, color: '#64748b', fontSize: 13 }}>班级范围</div>
          <Select
            style={{ width: '100%' }}
            value={exportClassKey}
            onChange={(value) => setExportClassKey(value as number | 'all')}
            options={[
              { value: 'all', label: '全部' },
              ...resources.classes.map(classOption),
            ]}
          />
        </div>
        <div>
          <div style={{ marginBottom: 6, color: '#64748b', fontSize: 13 }}>包含工作表</div>
          <Checkbox.Group
            style={{ display: 'grid', gap: 8 }}
            value={exportSheets}
            onChange={(values) => setExportSheets(values as string[])}
            options={[
              { value: 'cover', label: '说明' },
              { value: 'teacher_relation', label: '教师课时关系' },
              { value: 'teacher_hours', label: '教师课时' },
              { value: 'teacher_grid', label: '教师分课表' },
              { value: 'class_timetables', label: '各班课表' },
            ]}
          />
        </div>
      </Modal>

      <Modal
        title="已提交到文件中心"
        open={exportDoneOpen}
        onCancel={() => setExportDoneOpen(false)}
        centered
        width={440}
        destroyOnClose
        footer={[
          <Button key="stay" onClick={() => setExportDoneOpen(false)}>
            稍后查看
          </Button>,
          <Button
            key="go"
            type="primary"
            onClick={() => {
              setExportDoneOpen(false)
              navigate('/file-center')
            }}
          >
            前往文件中心
          </Button>,
        ]}
      >
        <p className="sk-adjustment-hint" style={{ marginBottom: 12 }}>
          任务已创建，可在文件中心查看进度并下载。
        </p>
        <div className="sk-export-done-meta">
          <div><span>操作</span><strong>{exportDoneInfo?.directionLabel || '导出'}</strong></div>
          <div><span>文件类型</span><strong>{exportDoneInfo?.jobTypeLabel || '导出排课完整包'}</strong></div>
          <div><span>范围</span><strong>{exportDoneInfo?.scope || '—'}</strong></div>
          {exportDoneInfo?.fileName ? (
            <div><span>文件名</span><strong>{exportDoneInfo.fileName}</strong></div>
          ) : null}
        </div>
      </Modal>

      <Modal
        title={adjustmentEntry ? `${adjustmentEntry.subject_name || '课程'} · ${adjustmentEntry.teacher_name || '未安排教师'} · 周${['一', '二', '三', '四', '五', '六', '日'][adjustmentEntry.weekday - 1]}第${adjustmentEntry.period}节` : '课程调整'}
        open={Boolean(adjustmentEntry)}
        onCancel={() => setAdjustmentEntry(undefined)}
        footer={null}
        centered
        width={adjustmentTab === 'move' ? 860 : 560}
        destroyOnClose
      >
        <div className="sk-adjustment-panel">
          <Tabs
            activeKey={adjustmentTab}
            onChange={(key) => setAdjustmentTab(key as 'move' | 'substitute')}
            items={[
              {
                key: 'move',
                label: '调课（换时段）',
                children: (() => {
                  const days = gridConfig.days || 6
                  const eveningStart = gridConfig.enable_evening
                    ? (gridConfig.evening_start_period ?? null)
                    : null
                  const dayColumns = days < 6
                    ? Array.from({ length: days }, (_, index) => ({
                        key: `d${index + 1}`,
                        label: `周${['一', '二', '三', '四', '五', '六', '日'][index]}`,
                        weekday: index + 1,
                        parity: 'all' as const,
                      }))
                    : [
                        ...[1, 2, 3, 4, 5].map((weekday) => ({
                          key: `d${weekday}`,
                          label: `周${['一', '二', '三', '四', '五'][weekday - 1]}`,
                          weekday,
                          parity: 'all' as const,
                        })),
                        { key: 'sat-odd', label: '单六', weekday: 6, parity: 'odd' as const },
                        { key: 'sat-even', label: '双六', weekday: 6, parity: 'even' as const },
                        ...(days >= 7
                          ? [{ key: 'd7', label: '周日', weekday: 7, parity: 'all' as const }]
                          : []),
                      ]
                  const daytimeEnd = eveningStart
                    ? Math.max(0, eveningStart - 1)
                    : (gridConfig.periods_per_day || 9)
                  const daytimePeriods = Array.from(
                    { length: daytimeEnd },
                    (_, index) => index + 1,
                  )
                  const optionMap = new Map(
                    adjustmentOptions.map((item) => [
                      `${item.weekday}-${item.period}-${item.week_parity || 'all'}`,
                      item,
                    ] as const),
                  )
                  const sourceParity = (adjustmentEntry?.week_parity || 'all') as 'all' | 'odd' | 'even'
                  const sourceIsSat = adjustmentEntry?.weekday === 6
                  const sourceIsEvening = Boolean(
                    eveningStart && adjustmentEntry && adjustmentEntry.period >= eveningStart,
                  )
                  const lookupOption = (
                    weekday: number,
                    period: number,
                    columnParity: 'all' | 'odd' | 'even',
                    rowParity?: 'odd' | 'even',
                  ) => {
                    if (rowParity) {
                      // 晚自习：工作日按行单双；周六按列单六/双六（左右单双都可点）
                      const parity = weekday === 6 && columnParity !== 'all'
                        ? columnParity
                        : rowParity
                      return optionMap.get(`${weekday}-${period}-${parity}`)
                        || optionMap.get(`${weekday}-${period}-all`)
                    }
                    if (columnParity === 'all') {
                      return optionMap.get(`${weekday}-${period}-${sourceParity}`)
                        || optionMap.get(`${weekday}-${period}-all`)
                    }
                    return optionMap.get(`${weekday}-${period}-${columnParity}`)
                      || optionMap.get(`${weekday}-${period}-all`)
                  }
                  const currentKey = adjustmentEntry
                    ? `${adjustmentEntry.weekday}-${adjustmentEntry.period}-${sourceParity}`
                    : ''
                  const renderCell = (
                    option: ScheduleAdjustmentOption | undefined,
                    key: string,
                    columnParity?: 'all' | 'odd' | 'even',
                    rowParity?: 'odd' | 'even',
                  ) => {
                    if (!option) {
                      return <div key={key} className="sk-adj-cell is-empty" />
                    }
                    const optionParity = (option.week_parity || 'all') as 'all' | 'odd' | 'even'
                    const optionKey = `${option.weekday}-${option.period}-${optionParity}`
                    const sameSlot = Boolean(adjustmentEntry)
                      && option.weekday === adjustmentEntry!.weekday
                      && option.period === adjustmentEntry!.period
                    // 整课/整晚：该节任一单双格都标当前；0.5 只标对应单双
                    const isCurrent = sameSlot && (
                      optionKey === currentKey
                      || sourceParity === 'all'
                      || (optionParity === 'all' && (
                        columnParity === sourceParity
                        || rowParity === sourceParity
                        || columnParity === 'all'
                        || !columnParity
                      ))
                    )
                    const selectable = option.selectable !== false && !isCurrent
                    const isSwap = option.mode === 'swap'
                    const peerSubject = (option.swap_with_subject || '').trim()
                    const peerTeacher = (option.swap_with_teacher || '').trim()
                    const blockedAsCollision = /(会撞课|已有其他班)/.test(option.reason || '')
                    let label: string
                    if (isCurrent) {
                      label = '当前'
                    } else if (peerSubject && (isSwap || blockedAsCollision)) {
                      if (!selectable && blockedAsCollision) label = `撞·${peerSubject}`
                      else if (!selectable) label = '—'
                      else if (option.available) label = peerSubject
                      else label = `${peerSubject}?`
                    } else if (!selectable) {
                      label = blockedAsCollision ? '撞课' : '—'
                    } else if (option.available) {
                      label = isSwap ? '对调' : '可调'
                    } else {
                      label = isSwap ? '对调?' : '有风险'
                    }
                    const tip = option.reason
                      || (peerSubject
                        ? `与「${peerSubject}」${peerTeacher ? `（${peerTeacher}）` : ''}对调`
                        : undefined)
                    const cell = (
                      <button
                        type="button"
                        className={[
                          'sk-adj-cell',
                          option.available && selectable && !isSwap ? 'is-available' : '',
                          option.available && selectable && isSwap ? 'is-swap' : '',
                          !option.available && selectable ? 'is-risky' : '',
                          !selectable && blockedAsCollision ? 'is-collision' : '',
                          !selectable && !blockedAsCollision && !isCurrent ? 'is-blocked' : '',
                          isCurrent ? 'is-current' : '',
                          peerSubject ? 'has-subject' : '',
                        ].filter(Boolean).join(' ')}
                        disabled={!selectable || movingSchedule || adjustPreviewLoading}
                        onClick={() => void openAdjustConfirm({
                          ...option,
                          // 整课/整晚必须带 all，避免点单六列时被写成 odd 拆掉双六
                          week_parity: sourceParity === 'all'
                            ? 'all'
                            : (option.week_parity || rowParity || columnParity || sourceParity),
                        })}
                      >
                        {label}
                      </button>
                    )
                    return tip ? (
                      <Tooltip key={key} title={tip} placement="top">
                        <span className="sk-adj-cell-wrap">{cell}</span>
                      </Tooltip>
                    ) : (
                      <span key={key} className="sk-adj-cell-wrap">{cell}</span>
                    )
                  }
                  const blockedOption = (
                    weekday: number,
                    period: number,
                    parity: 'all' | 'odd' | 'even',
                    reason: string,
                  ): ScheduleAdjustmentOption => ({
                    weekday,
                    period,
                    week_parity: parity,
                    available: false,
                    selectable: false,
                    reason,
                    mode: 'move',
                    checks: [],
                  })
                  const renderDaytimeColumns = (period: number) => {
                    const nodes: React.ReactNode[] = []
                    for (const column of dayColumns) {
                      const option = lookupOption(column.weekday, period, column.parity)
                      if (option) {
                        nodes.push(renderCell(option, `${column.key}-${period}`, column.parity))
                        continue
                      }
                      let reason = '不在可调范围内'
                      if (sourceIsSat && column.weekday <= 5) reason = '周六课不能调到工作日'
                      else if (!sourceIsSat && column.weekday === 6) reason = '工作日课不能调到单六/双六'
                      nodes.push(renderCell(
                        blockedOption(
                          column.weekday,
                          period,
                          column.parity === 'all' ? sourceParity : column.parity,
                          reason,
                        ),
                        `${column.key}-${period}`,
                        column.parity,
                      ))
                    }
                    return nodes
                  }
                  const renderEveningColumns = (rowParity: 'odd' | 'even') => {
                    const nodes: React.ReactNode[] = []
                    for (const column of dayColumns) {
                      // 周六晚：单六列只展示在单周行、双六列只展示在双周行，避免同一选项占两格
                      if (
                        column.weekday === 6
                        && column.parity !== 'all'
                        && column.parity !== rowParity
                      ) {
                        nodes.push(
                          <div
                            key={`evening-${rowParity}-${column.key}`}
                            className="sk-adj-cell is-empty"
                          />,
                        )
                        continue
                      }
                      const option = lookupOption(column.weekday, eveningStart!, column.parity, rowParity)
                      if (option) {
                        nodes.push(renderCell(
                          option,
                          `evening-${rowParity}-${column.key}`,
                          column.parity,
                          rowParity,
                        ))
                        continue
                      }
                      const blockParity = column.weekday === 6 && column.parity !== 'all'
                        ? column.parity
                        : rowParity
                      nodes.push(renderCell(
                        blockedOption(
                          column.weekday,
                          eveningStart!,
                          blockParity,
                          sourceIsEvening ? '不在可调范围内' : '晚自习不能与白天课对调',
                        ),
                        `evening-${rowParity}-${column.key}`,
                        column.parity,
                        rowParity,
                      ))
                    }
                    return nodes
                  }
                  return (
                    <>
                      <p className="sk-adjustment-hint">
                        整课（单双相同）两格一起动，不会拆成单侧。0.5 课时可在单六↔双六（或晚自习单↔双）间挪。点格子后右侧全部 √ 才能确认。
                      </p>
                      {adjustmentLoading ? (
                        <EmptyState icon="calendar" title="正在计算可调时段…" height={160} />
                      ) : adjustmentOptions.length === 0 ? (
                        <EmptyState icon="calendar" title="没有可调时段" height={140} />
                      ) : (
                        <div
                          className="sk-adjustment-grid"
                          style={{ '--adj-days': dayColumns.length } as CSSProperties}
                        >
                          <div className="sk-adj-corner">节次</div>
                          {dayColumns.map((column) => (
                            <div key={`head-${column.key}`} className="sk-adj-day-head">
                              {column.label}
                            </div>
                          ))}
                          {daytimePeriods.map((period) => [
                            <div key={`period-${period}`} className="sk-adj-period">
                              第{period}节
                            </div>,
                            ...renderDaytimeColumns(period),
                          ])}
                          {eveningStart
                            ? (['odd', 'even'] as const).map((rowParity) => [
                                <div key={`evening-${rowParity}`} className="sk-adj-period sk-adj-evening">
                                  <strong>晚自习</strong>
                                  <small>{rowParity === 'odd' ? '单周' : '双周'}</small>
                                </div>,
                                ...renderEveningColumns(rowParity),
                              ])
                            : null}
                        </div>
                      )}
                    </>
                  )
                })(),
              },
              {
                key: 'substitute',
                label: '代课（换老师）',
                children: (
                  <>
                    <p className="sk-adjustment-hint">本学期教该学科、且此时段没课的老师；按当前周课时从少到多排列，适合病假、事假临时顶课。</p>
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

      <Modal
        title={
          adjustPreview?.mode === 'swap'
            ? `确认对调 · 周${['一', '二', '三', '四', '五', '六', '日'][(adjustPreview.weekday || 1) - 1]}第${adjustPreview.period}节`
            : adjustPreview
              ? `确认调课 · 周${['一', '二', '三', '四', '五', '六', '日'][adjustPreview.weekday - 1]}第${adjustPreview.period}节`
              : '确认调整'
        }
        open={adjustConfirmOpen}
        onCancel={() => {
          if (movingSchedule) return
          setAdjustConfirmOpen(false)
          setAdjustPreview(null)
        }}
        okText="确认调整"
        cancelText="取消"
        confirmLoading={movingSchedule}
        okButtonProps={{ disabled: !allChecksAcknowledged || adjustPreviewLoading }}
        onOk={() => void confirmMoveEntry()}
        centered
        width={560}
        destroyOnClose
      >
        {adjustPreviewLoading || !adjustPreview ? (
          <EmptyState icon="calendar" title="正在核对检查项…" height={160} />
        ) : (
          <div className="sk-adjust-check-panel">
            <p className="sk-adjustment-hint">
              {adjustPreview.mode === 'swap'
                ? `将与「${adjustPreview.swap_with_subject || '对方课程'}」${adjustPreview.swap_with_teacher ? `（${adjustPreview.swap_with_teacher}）` : ''}对调。`
                : '将挪到该空时段。'}
              通过项已默认打勾；未通过项为后端按「调整后课表」校验出的新增问题，需手动点成 √ 后才能确认。
            </p>
            <ul className="sk-adjust-check-list">
              {(adjustPreview.checks || []).map((item) => {
                const acknowledged = Boolean(acknowledgedChecks[item.key])
                return (
                  <li key={item.key} className={item.passed ? 'is-pass' : 'is-fail'}>
                    <div className="sk-adjust-check-main">
                      <span className="sk-adjust-check-system" title={item.passed ? '系统判定通过' : '系统判定未通过'}>
                        {item.passed ? '通过' : '未通过'}
                      </span>
                      <span className="sk-adjust-check-label">{item.label}</span>
                    </div>
                    <button
                      type="button"
                      className={`sk-adjust-ack${acknowledged ? ' is-on' : ''}`}
                      onClick={() =>
                        setAcknowledgedChecks((prev) => ({
                          ...prev,
                          [item.key]: !prev[item.key],
                        }))
                      }
                      aria-label={acknowledged ? '已确认' : '点击确认为√'}
                    >
                      {acknowledged ? '√' : '✗'}
                    </button>
                  </li>
                )
              })}
            </ul>
            {!allChecksAcknowledged && (
              <p className="sk-adjust-check-tip">还有未点成 √ 的项，确认按钮暂不可用。</p>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
