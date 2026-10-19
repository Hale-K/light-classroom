import { translate as t, useLocale } from '@/i18n'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { App, Button, InputNumber, Modal, Pagination, Radio, Select, Space, Tabs, Tag } from 'antd'
import { authApi, type AcademicYearEntry, type AcademicYearRolloverPreview, type SchoolSettings } from '@/api'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import './school-settings-form.css'
import { ACADEMIC_CONTEXT_CHANGED } from '@/utils/academicContext'
import { useSearchParams } from 'react-router-dom'
import type { EducationStage } from '@/types'

type GaokaoMode = '3+1+2' | '3+3' | 'traditional'
type TimetableMode = 'administrative' | 'walk_class'
type CohortStatus = AcademicYearEntry['status']
type BasicKey = 'province' | 'gaokao_mode' | 'timetable_mode' | 'current_entry_year' | 'current_academic_year' | 'current_term' | 'head_teacher_max_lead'

const PROVINCES = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海',
  '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
  '广东', '广西', '海南', '重庆', '四川', '贵州', '云南', '西藏', '陕西',
  '甘肃', '青海', '宁夏', '新疆',
]

const MODES: Array<{ value: GaokaoMode; label: string; note: string }> = [
  { value: '3+1+2', label: '3+1+2', note: '物理/历史首选一门，其余四科再选两门' },
  { value: '3+3', label: '3+3', note: '语数外以外，从配置的选考科目中选择三门' },
  { value: 'traditional', label: '传统文理', note: '按文科、理科组织行政班教学' },
]

const TIMETABLE_MODES: Array<{ value: TimetableMode; label: string; note: string }> = [
  { value: 'administrative', label: '固定班级课表', note: '按行政班或固定班级统一排课' },
  { value: 'walk_class', label: '分组走班课表', note: '按教学班、选课或分组结果生成学生课表' },
]

interface StagePresentation {
  gradeNames: string[]
  cohortLabel: string
  cohortTabLabel: string
  currentCohortTitle: string
}

const STAGE_PRESENTATIONS: Record<EducationStage, StagePresentation> = {
  primary: {
    gradeNames: ['一年级', '二年级', '三年级', '四年级', '五年级', '六年级'],
    cohortLabel: '入学年级',
    cohortTabLabel: '入学年级管理',
    currentCohortTitle: '当前一年级入学年',
  },
  junior: {
    gradeNames: ['初一', '初二', '初三'],
    cohortLabel: '入学年级',
    cohortTabLabel: '入学年级管理',
    currentCohortTitle: '当前初一入学年',
  },
  senior: {
    gradeNames: ['高一', '高二', '高三'],
    cohortLabel: '届别',
    cohortTabLabel: '届次管理',
    currentCohortTitle: '当前高一届别',
  },
  higher: {
    gradeNames: [],
    cohortLabel: '培养周期',
    cohortTabLabel: '培养周期',
    currentCohortTitle: '当前培养周期',
  },
  training: {
    gradeNames: [],
    cohortLabel: '培训批次',
    cohortTabLabel: '培训批次',
    currentCohortTitle: '当前培训批次',
  },
}

const academicYearAt = (entryYear: number, offset: number) =>
  `${entryYear + offset}-${entryYear + offset + 1}`

const stageGradeYears = (entryYear: number, stage: EducationStage) =>
  STAGE_PRESENTATIONS[stage].gradeNames.map((name, index) => ({
    name,
    academicYear: academicYearAt(entryYear, index),
  }))

const cohortDisplayName = (entryYear: number, stage: EducationStage) =>
  stage === 'senior' ? `${entryYear}届` : `${entryYear}级`

const STATUS_LABEL: Record<CohortStatus, string> = {
  active: '启用中',
  inactive: '已归档',
}

const buildCohortRow = (entryYear: number, status: CohortStatus = 'active'): AcademicYearEntry => ({
  entry_year: entryYear,
  cohort_label: `${entryYear}届`,
  grade_years: {
    高一: `${entryYear}-${entryYear + 1}`,
    高二: `${entryYear + 1}-${entryYear + 2}`,
    高三: `${entryYear + 2}-${entryYear + 3}`,
  },
  status,
})

interface Props {
  onSaved?: () => void
  gradePanel?: ReactNode
}

export default function SchoolSettingsForm({ onSaved, gradePanel }: Props) {
  const locale = useLocale()
  const { message, modal } = App.useApp()
  const [settings, setSettings] = useState<SchoolSettings | null>(null)
  const stage = settings?.education_stage ?? 'senior'
  const presentation = STAGE_PRESENTATIONS[stage]
  const [academicYears, setAcademicYears] = useState<AcademicYearEntry[]>([])
  const [currentEntryYear, setCurrentEntryYear] = useState<number>()
  const [currentAcademicYear, setCurrentAcademicYear] = useState<string>()
  const [currentTerm, setCurrentTerm] = useState<'1' | '2'>('1')
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState<'basic' | 'cohorts' | 'grades'>(requestedTab === 'cohorts' || requestedTab === 'grades' ? requestedTab : 'basic')

  // 新建届别弹窗
  const [cohortModalOpen, setCohortModalOpen] = useState(false)
  const [editingEntryYear, setEditingEntryYear] = useState<number | undefined>()
  const [cohortYear, setCohortYear] = useState<number>(new Date().getFullYear())
  const [rolloverOpen, setRolloverOpen] = useState(false)
  const [rolloverPreview, setRolloverPreview] = useState<AcademicYearRolloverPreview | null>(null)
  const [rolloverLoading, setRolloverLoading] = useState(false)

  // 编辑基础配置弹窗
  const [editingKey, setEditingKey] = useState<BasicKey | null>(null)
  const [editDraft, setEditDraft] = useState<any>()
  // 所有学年学期写入串行化，防止连续点击时旧请求后返回并覆盖新配置。
  const saveChainRef = useRef<Promise<unknown>>(Promise.resolve())

  const openRollover = async () => {
    if (currentEntryYear === undefined) return
    setRolloverOpen(true)
    setRolloverLoading(true)
    try {
      setRolloverPreview(await authApi.previewAcademicYearRollover(currentEntryYear))
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("学年滚动预览失败"))
      setRolloverOpen(false)
    } finally {
      setRolloverLoading(false)
    }
  }

  const commitRollover = async () => {
    if (!rolloverPreview) return
    setRolloverLoading(true)
    try {
      const result = await authApi.commitAcademicYearRollover(rolloverPreview.source_entry_year)
      const refreshed = await authApi.academicYears()
      setAcademicYears(refreshed.years)
      setCurrentEntryYear(refreshed.current_entry_year ?? undefined)
      setCurrentAcademicYear(refreshed.current_academic_year ?? undefined)
      setCurrentTerm(refreshed.current_term)
      setRolloverOpen(false)
      message.success(t("已进入 {{p0}}，晋级 {{p1}} 名学生", { p0: result.current_academic_year, p1: result.promoted_student_count }))
      onSaved?.()
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("学年滚动失败"))
    } finally {
      setRolloverLoading(false)
    }
  }

  useEffect(() => {
    Promise.all([authApi.school(), authApi.academicYears()])
      .then(([school, yearSettings]) => {
        setSettings(school)
        setAcademicYears(yearSettings.years)
        setCurrentEntryYear(yearSettings.current_entry_year ?? undefined)
        setCurrentAcademicYear(yearSettings.current_academic_year ?? undefined)
        setCurrentTerm(yearSettings.current_term ?? '1')
      })
      .catch((e) => message.error(e instanceof Error ? e.message : t("学校信息加载失败")))
  }, [message])

  useEffect(() => {
    if (settings && presentation.gradeNames.length === 0 && activeTab !== 'basic') {
      setActiveTab('basic')
      setSearchParams({}, { replace: true })
    }
  }, [settings, presentation.gradeNames.length, activeTab, setSearchParams])

  const refreshAcademicContext = async () => {
    const yearSettings = await authApi.academicYears()
    setAcademicYears(yearSettings.years)
    setCurrentEntryYear(yearSettings.current_entry_year ?? undefined)
    setCurrentAcademicYear(yearSettings.current_academic_year ?? undefined)
    setCurrentTerm(yearSettings.current_term ?? '1')
  }

  useEffect(() => {
    const handleAcademicContextChanged = () => {
      void refreshAcademicContext().catch(() => undefined)
    }
    window.addEventListener(ACADEMIC_CONTEXT_CHANGED, handleAcademicContextChanged)
    return () => window.removeEventListener(ACADEMIC_CONTEXT_CHANGED, handleAcademicContextChanged)
  }, [])

  /** 统一把当前届次/学年/学期提交给后端，保持前后端同步 */
  const persistCurrent = (
    nextYears?: AcademicYearEntry[],
    entryYear?: number,
    academicYear?: string,
    term?: '1' | '2',
  ) => {
    const save = saveChainRef.current.then(async () => {
      // 未显式传入的字段一律以保存前刚读取的后端值为准，避免闭包里的旧 state 覆盖配置。
      const latest = await authApi.academicYears()
      const years = nextYears ?? latest.years
      const result = await authApi.saveAcademicYears(
        years.map((item) => ({ entry_year: item.entry_year, status: item.status })),
        entryYear ?? latest.current_entry_year,
        academicYear ?? latest.current_academic_year,
        term ?? latest.current_term,
      )
      setAcademicYears(result.years)
      setCurrentEntryYear(result.current_entry_year ?? undefined)
      setCurrentAcademicYear(result.current_academic_year ?? undefined)
      setCurrentTerm(result.current_term ?? '1')
      window.dispatchEvent(new CustomEvent(ACADEMIC_CONTEXT_CHANGED, { detail: result }))
      return result
    })
    saveChainRef.current = save.catch(() => undefined)
    return save
  }

  /** 基础配置 5 条规则数据 */
  const basicRules = useMemo(() => {
    const curCohort = academicYears.find((item) => item.entry_year === currentEntryYear)
    const stage = settings?.education_stage ?? 'senior'
    const presentation = STAGE_PRESENTATIONS[stage]
    const gradeYears = curCohort ? stageGradeYears(curCohort.entry_year, stage) : []
    const firstGrade = gradeYears[0]
    const lastGrade = gradeYears.at(-1)
    const rules = [
      {
        key: 'province' as BasicKey,
        icoColor: 'blue',
        icoName: 'building',
        title: t("学校所在省份"),
        chipColor: 'blue',
        chipLabel: settings?.province || t("未设置"),
        modeTag: '',
        desc: settings?.province
          ? t(stage === 'senior' ? "用于选科方案和考务信息。" : "用于学校信息、课程与考务配置。")
          : t("未设置，请编辑。"),
      },
      {
        key: 'gaokao_mode' as BasicKey,
        icoColor: 'purple',
        icoName: 'book',
        title: t("默认高考模式"),
        chipColor: 'purple',
        chipLabel: (MODES.find((item) => item.value === settings?.gaokao_mode)?.label) || t("未设置"),
        modeTag: MODES.find((item) => item.value === settings?.gaokao_mode)?.note || '',
        desc: MODES.find((item) => item.value === settings?.gaokao_mode)
          ? t("新建届别会沿用此模式；已建届别可单独修改。")
          : t("未设置，请编辑。"),
      },
      {
        key: 'current_entry_year' as BasicKey,
        icoColor: 'green',
        icoName: 'school' as any,
        title: t(presentation.currentCohortTitle),
        chipColor: 'green',
        chipLabel: curCohort ? cohortDisplayName(curCohort.entry_year, stage) : t("未设置"),
        modeTag: firstGrade ? `${firstGrade.name}：${firstGrade.academicYear}` : '',
        desc: firstGrade && lastGrade
          ? `${t("覆盖")} ${firstGrade.name} ${t("至")} ${lastGrade.name}：${firstGrade.academicYear} ${t("至")} ${lastGrade.academicYear}`
          : t("未设置，请在入学年级管理中新建。"),
      },
      {
        key: 'timetable_mode' as BasicKey,
        icoColor: 'cyan',
        icoName: 'calendar',
        title: t("课表模式"),
        chipColor: 'cyan',
        chipLabel: TIMETABLE_MODES.find((item) => item.value === settings?.timetable_mode)?.label || t("未设置"),
        modeTag: TIMETABLE_MODES.find((item) => item.value === settings?.timetable_mode)?.note || '',
        desc: settings?.timetable_mode === 'walk_class'
          ? t("学生课表按教学班选课结果生成。")
          : t("按行政班统一安排课程。"),
      },
      {
        key: 'current_academic_year' as BasicKey,
        icoColor: 'orange',
        icoName: 'calendar',
        title: t("当前学年"),
        chipColor: 'orange',
        chipLabel: currentAcademicYear || t("未设置"),
        modeTag: '',
        desc: currentAcademicYear ? '' : t(`未设置，请先建立${presentation.cohortLabel}。`),
      },
      {
        key: 'current_term' as BasicKey,
        icoColor: 'pink',
        icoName: 'circle-check',
        title: t("当前学期"),
        chipColor: 'pink',
        chipLabel: currentTerm === '1' ? t("上学期") : t("下学期"),
        modeTag: currentTerm === '1' ? t("第 1 学期") : t("第 2 学期"),
        desc: t("新建排课、考试和考勤默认使用此学期。"),
      },
    ]
    return settings?.education_stage === 'senior'
      ? rules
      : rules.filter((rule) => rule.key !== 'gaokao_mode' && (
        presentation.gradeNames.length > 0 || rule.key !== 'current_entry_year'
      ))
  }, [settings, academicYears, currentEntryYear, currentAcademicYear, currentTerm, locale])

  const openEditBasic = (key: BasicKey) => {
    setEditingKey(key)
    switch (key) {
      case 'province':
        setEditDraft(settings?.province)
        break
      case 'gaokao_mode':
        setEditDraft(settings?.gaokao_mode)
        break
      case 'current_entry_year':
        setEditDraft(currentEntryYear)
        break
      case 'timetable_mode':
        setEditDraft(settings?.timetable_mode || 'administrative')
        break
      case 'current_academic_year':
        setEditDraft(currentAcademicYear)
        break
      case 'current_term':
        setEditDraft(currentTerm)
        break
    }
  }

  const submitBasicEdit = async () => {
    if (!editingKey) return
    try {
      if (editingKey === 'province' || editingKey === 'gaokao_mode' || editingKey === 'timetable_mode') {
        const patch: any = {}
        if (editingKey === 'province') patch.province = editDraft as string
        if (editingKey === 'gaokao_mode') patch.gaokao_mode = editDraft as GaokaoMode
        if (editingKey === 'timetable_mode') patch.timetable_mode = editDraft as TimetableMode
        const next = await authApi.updateSchool(patch)
        setSettings((prev) => (prev ? { ...prev, ...next } : next))
        await persistCurrent()
      } else {
        const years = academicYears
        let entry: number | undefined = currentEntryYear
        let year: string | undefined = currentAcademicYear
        let term: '1' | '2' = currentTerm
        if (editingKey === 'current_entry_year') {
          entry = Number(editDraft)
          const row = academicYears.find((item) => item.entry_year === entry)
          year = row ? academicYearAt(row.entry_year, 0) : year
        } else if (editingKey === 'current_academic_year') {
          year = String(editDraft)
        } else if (editingKey === 'current_term') {
          term = editDraft as '1' | '2'
        }
        await persistCurrent(years, entry, year, term)
      }
      message.success(t("配置已更新"))
      setEditingKey(null)
      onSaved?.()
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("保存失败"))
    }
  }

  const openNewCohort = () => {
    setEditingEntryYear(undefined)
    setCohortYear((currentEntryYear ?? new Date().getFullYear()) + 1)
    setCohortModalOpen(true)
  }

  const openEditCohort = (item: AcademicYearEntry) => {
    setEditingEntryYear(item.entry_year)
    setCohortYear(item.entry_year)
    setCohortModalOpen(true)
  }

  const submitCohort = async () => {
    if (!cohortYear) {
      message.warning(t(`请填写${presentation.cohortLabel}年份`))
      return
    }
    const exists = academicYears.some((item) => item.entry_year === cohortYear)
    if (!editingEntryYear && exists) {
      message.warning(t(`${cohortDisplayName(cohortYear, stage)}已经存在`))
      return
    }
    let nextYears: AcademicYearEntry[]
    if (editingEntryYear && editingEntryYear !== cohortYear) {
      nextYears = [
        ...academicYears.filter((item) => item.entry_year !== editingEntryYear && item.entry_year !== cohortYear),
        buildCohortRow(cohortYear, 'active'),
      ]
    } else if (editingEntryYear) {
      setCohortModalOpen(false)
      return
    } else {
      nextYears = [
        ...academicYears.filter((item) => item.entry_year !== cohortYear),
        buildCohortRow(cohortYear, 'active'),
      ]
    }
    nextYears.sort((a, b) => b.entry_year - a.entry_year)
    try {
      const nextEntryYear = currentEntryYear ?? nextYears[0]?.entry_year
      await persistCurrent(nextYears, nextEntryYear)
      message.success(editingEntryYear ? t(`${presentation.cohortLabel}已更新`) : t(`${presentation.cohortLabel}已创建`))
      setCohortModalOpen(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : t(`${presentation.cohortLabel}保存失败`))
    }
  }

  const setAsCurrentCohort = async (item: AcademicYearEntry) => {
    try {
      await persistCurrent(academicYears, item.entry_year, `${item.entry_year}-${item.entry_year + 1}`)
      message.success(t(`已切换到 ${cohortDisplayName(item.entry_year, stage)} · ${academicYearAt(item.entry_year, 0)}学年`))
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("切换失败"))
    }
  }

  const toggleCohortStatus = async (item: AcademicYearEntry) => {
    const nextStatus: CohortStatus = item.status === 'active' ? 'inactive' : 'active'
    const nextYears = academicYears.map((row) =>
      row.entry_year === item.entry_year ? { ...row, status: nextStatus } : row,
    )
    try {
      await persistCurrent(nextYears)
      message.success(t("{{p0}} 已{{p1}}", { p0: item.cohort_label, p1: nextStatus === 'active' ? t("启用") : t("归档") }))
    } catch (e) {
      message.error(e instanceof Error ? e.message : t("操作失败"))
    }
  }

  const removeCohort = async (item: AcademicYearEntry) => {
    if (currentEntryYear === item.entry_year) {
      message.warning(t(`当前${presentation.cohortLabel}无法删除，请先切换到其他${presentation.cohortLabel}`))
      return
    }
    modal.confirm({
      title: t(`确认删除 ${cohortDisplayName(item.entry_year, stage)}？`),
      content: t(`删除后，该${presentation.cohortLabel}与排课、班级相关的历史配置将不再引用，操作不可恢复。`),
      okType: 'danger',
      onOk: async () => {
        const nextYears = academicYears.filter((row) => row.entry_year !== item.entry_year)
        await persistCurrent(nextYears)
        message.success(t(`${presentation.cohortLabel}已删除`))
      },
    })
  }

  const allAcademicYearOptions = useMemo(() => {
    const set = new Set<string>()
    const stage = settings?.education_stage ?? 'senior'
    academicYears.forEach((item) => {
      stageGradeYears(item.entry_year, stage).forEach((grade) => set.add(grade.academicYear))
    })
    return Array.from(set).sort().reverse()
  }, [academicYears, settings?.education_stage, locale])

  const [cohortPage, setCohortPage] = useState(1)
  const COHORT_PAGE_SIZE = 6
  const paginatedCohorts = useMemo(() => {
    const start = (cohortPage - 1) * COHORT_PAGE_SIZE
    return academicYears.slice(start, start + COHORT_PAGE_SIZE)
  }, [academicYears, cohortPage, locale])

  if (!settings) return null
  const currentCohort = academicYears.find((item) => item.entry_year === currentEntryYear)
  const currentGradeYears = currentEntryYear ? stageGradeYears(currentEntryYear, stage) : []
  const firstGrade = currentGradeYears[0]
  const hasGradeProgression = presentation.gradeNames.length > 0

  return (
    <div className="ssf-form-v2">
      {/* 顶部标题 */}
      <div className="ssf-page-head">
        <div className="ssf-page-head-title">
          <h1>{t("系统设置")} <Tag color="blue">{settings.education_stage_label}</Tag></h1>
        </div>
      </div>

      {/* 当前生效概览卡 */}
      <div className="ssf-brief">
        {hasGradeProgression && (
          <div className="ssf-brief-card active">
            <span>{t(`当前${presentation.cohortLabel}`)}</span>
            <strong>{currentCohort ? cohortDisplayName(currentCohort.entry_year, stage) : t("未设置")}</strong>
            <small>{firstGrade ? `${firstGrade.name}学年：${firstGrade.academicYear}` : t("请新建入学年级")}</small>
          </div>
        )}
        <div className="ssf-brief-card">
          <span>{t("当前学年")}</span>
          <strong>{currentAcademicYear || t("未设置")}</strong>
          <small>{t(stage === 'senior' ? "排课 / 选科默认学年" : "教学与课表默认学年")}</small>
        </div>
        <div className="ssf-brief-card">
          <span>{t("当前学期")}</span>
          <strong>{currentTerm === '1' ? t("第一学期") : t("第二学期")}</strong>
          <small>{t("新建排课默认学期")}</small>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        className="ssf-tabs"
        activeKey={activeTab}
        onChange={(k: string) => {
          const next = k as 'basic' | 'cohorts' | 'grades'
          setActiveTab(next)
          setSearchParams(next === 'basic' ? {} : { tab: next }, { replace: true })
        }}
        items={[
          {
            key: 'basic',
            label: t("基础配置"),
            children: (
              <div className="ssf-rule-card">
                <div className="ssf-rule-head">
                  <div>{t("配置项")}</div>
                  <div>{t("当前值")}</div>
                  <div>{t("标记")}</div>
                  <div>{t("影响")}</div>
                  <div style={{ textAlign: 'right' }}>{t("操作")}</div>
                </div>
                {basicRules.map((rule) => (
                  <div key={rule.key} className="ssf-rule-row">
                    <div className="ssf-rule-name">
                      <span className={`ssf-rule-ico ${rule.icoColor}`}>
                        <Icon name={rule.icoName as any} size={16} />
                      </span>
                      <span className="ssf-rule-text">
                        <strong>
                          {rule.title}
                          {rule.key === 'current_entry_year' && currentEntryYear !== undefined && (
                            <Tag color="blue">{t("当前")}</Tag>
                          )}
                        </strong>
                      </span>
                    </div>
                    <div>
                      <span className={`ssf-rule-chip ${rule.chipColor}`}>{rule.chipLabel}</span>
                    </div>
                    <div>
                      {rule.modeTag ? <span className="ssf-rule-chip">{rule.modeTag}</span> : <span style={{ color: 'var(--text-3)', fontSize: 12 }}>—</span>}
                    </div>
                    <div className="ssf-rule-desc">{rule.desc}</div>
                    <div className="ssf-rule-actions">
                      <Button type="link" size="small" onClick={() => openEditBasic(rule.key)}>{t("编辑")}</Button>
                    </div>
                  </div>
                ))}
              </div>
            ),
          },
          ...(hasGradeProgression ? [{
            key: 'cohorts',
            label: t(presentation.cohortTabLabel),
            children: (
              <div className="ssf-rule-card">
                <div className="ssf-rule-subnav">
                  <div>
                    <h2>{t(`${presentation.cohortLabel}清单`)}</h2>
                    <p>{t(`每创建一个${presentation.cohortLabel}，系统会按${presentation.gradeNames.join('→')}展示对应学年，用于排课和学生列表。`)}</p>
                  </div>
                  <Space>
                    {stage === 'senior' && <Button onClick={openRollover} disabled={currentEntryYear === undefined}>{t("进入下一学年")}</Button>}
                    <Button type="primary" size="large" icon={<Icon name="plus" size={14} />} onClick={openNewCohort}>{t(`新建${presentation.cohortLabel}`)}</Button>
                  </Space>
                </div>
                <div className="ssf-rule-head">
                  <div>{t(`${presentation.cohortLabel}名称`)}</div>
                  <div>{t(`${presentation.gradeNames.at(-1)}学年`)}</div>
                  <div>{t("状态")}</div>
                  <div>{t("说明")}</div>
                  <div style={{ textAlign: 'right' }}>{t("操作")}</div>
                </div>
                {paginatedCohorts.length === 0 ? (
                  <div className="ssf-empty">
                    <EmptyState
                      height={180}
                      title={t(`暂无${presentation.cohortLabel}`)}
                      desc={t(`点击上方「新建${presentation.cohortLabel}」开始配置`)}
                    />
                  </div>
                ) : (
                  paginatedCohorts.map((record) => {
                    const gradeYears = stageGradeYears(record.entry_year, stage)
                    const first = gradeYears[0]
                    const last = gradeYears.at(-1)
                    return (
                    <div key={record.entry_year} className="ssf-rule-row">
                      <div className="ssf-rule-name">
                      <span className={`ssf-rule-ico ${currentEntryYear === record.entry_year ? 'green' : 'purple'}`}>
                        <Icon name="school" size={16} />
                      </span>
                        <span className="ssf-rule-text">
                          <strong>
                            {cohortDisplayName(record.entry_year, stage)}
                            {currentEntryYear === record.entry_year && (
                              <Tag color="blue">{t("默认")}</Tag>
                            )}
                          </strong>
                          <small>{first?.name}：{first?.academicYear}</small>
                        </span>
                      </div>
                      <div>
                        <span className="ssf-rule-chip purple">{last?.academicYear}</span>
                      </div>
                      <div>
                        <Tag color={record.status === 'active' ? 'green' : 'default'}>
                          {STATUS_LABEL[record.status]}
                        </Tag>
                      </div>
                      <div className="ssf-rule-desc">
                        {cohortDisplayName(record.entry_year, stage)}：{first?.name} {first?.academicYear} → {last?.name} {last?.academicYear}</div>
                      <div className="ssf-rule-actions">
                        <Space size={2}>
                          <Button
                            type="text"
                            size="small"
                            disabled={currentEntryYear === record.entry_year}
                            title={t(`设为当前${presentation.cohortLabel}`)}
                            onClick={() => setAsCurrentCohort(record)}
                          >
                            <Icon name="star" size={14} />
                          </Button>
                          <Button
                            type="text"
                            size="small"
                            title={t("编辑")}
                            onClick={() => openEditCohort(record)}
                          >
                            <Icon name="edit" size={14} />
                          </Button>
                          <Button
                            type="text"
                            size="small"
                            onClick={() => toggleCohortStatus(record)}
                          >
                            <Icon name="rotate" size={14} />
                          </Button>
                          <Button
                            type="text"
                            size="small"
                            danger
                            onClick={() => removeCohort(record)}
                          >
                            <Icon name="trash" size={14} />
                          </Button>
                        </Space>
                      </div>
                    </div>
                    )
                  })
                )}
                {academicYears.length > 0 && (
                  <div className="ssf-pagination">
                    {t("共")}{academicYears.length} {t(`个${presentation.cohortLabel}`)}<Pagination
                      size="small"
                      current={cohortPage}
                      pageSize={COHORT_PAGE_SIZE}
                      total={academicYears.length}
                      showSizeChanger={false}
                      onChange={setCohortPage}
                    />
                  </div>
                )}
              </div>
            ),
          }] : []),
          ...(gradePanel && hasGradeProgression
            ? [{
                key: 'grades',
                label: t("年级数据"),
                children: gradePanel,
              }]
            : []),
        ]}
      />

      <Modal
        title={t("进入下一学年")}
        open={rolloverOpen}
        onCancel={() => setRolloverOpen(false)}
        footer={rolloverPreview && !rolloverPreview.already_done ? [
          <Button key="cancel" onClick={() => setRolloverOpen(false)}>{t("取消")}</Button>,
          <Button key="confirm" type="primary" loading={rolloverLoading} onClick={commitRollover}>{t("确认滚动")}</Button>,
        ] : [<Button key="close" onClick={() => setRolloverOpen(false)}>{t("关闭")}</Button>]}
        width={640}
        centered
        destroyOnClose
      >
        {rolloverLoading && !rolloverPreview ? <div style={{ padding: 36, textAlign: 'center' }}>{t("正在计算滚动预览…")}</div> : rolloverPreview && (
          <div className="ssf-form-modal">
            <div className="ssf-brief" style={{ gridTemplateColumns: '1fr 1fr', margin: 0 }}>
              <div className="ssf-brief-card"><span>{t("当前学年")}</span><strong>{rolloverPreview.source_academic_year}</strong><small>{rolloverPreview.source_cohort_label}</small></div>
              <div className="ssf-brief-card active"><span>{t("滚动后")}</span><strong>{rolloverPreview.target_academic_year}</strong><small>{rolloverPreview.target_cohort_label}</small></div>
            </div>
            <div className="ssf-rule-card" style={{ marginTop: 16 }}>
              <div className="ssf-rule-row"><strong>{t("待处理学生")}</strong><span>{rolloverPreview.student_count} {t("人")}</span></div>
              <div className="ssf-rule-row"><strong>{t("高一 → 高二")}</strong><span>{rolloverPreview.promote_high_one_classes} {t("个班")}</span></div>
              <div className="ssf-rule-row"><strong>{t("高二 → 高三")}</strong><span>{rolloverPreview.promote_high_two_classes} {t("个班")}</span></div>
              <div className="ssf-rule-row"><strong>{t("高三毕业")}</strong><span>{rolloverPreview.graduate_high_three_classes} {t("个班")}</span></div>
            </div>
            {rolloverPreview.warnings.map((warning) => <div key={warning} style={{ color: '#b7791f', marginTop: 14 }}>{warning}</div>)}
            {rolloverPreview.already_done && <div style={{ color: '#b42318', marginTop: 14 }}>{t("该届别已经执行过滚动，不能重复执行。")}</div>}
          </div>
        )}
      </Modal>

      {/* 基础配置编辑弹窗 */}
      <Modal
        title={t("编辑：{{p0}}", { p0: basicRules.find((r) => r.key === editingKey)?.title || '' })}
        open={editingKey !== null}
        onOk={submitBasicEdit}
        onCancel={() => setEditingKey(null)}
        okText={t("保存")}
        cancelText={t("取消")}
        width={460}
        destroyOnClose
      >
        <div className="ssf-form-modal">
          {editingKey === 'province' && (
            <label className="ssf-label">
              {t("学校所在省份")}<Select
                showSearch
                value={editDraft}
                onChange={setEditDraft}
                placeholder={t("选择省份")}
                options={PROVINCES.map((p) => ({ label: p, value: p }))}
              />
            </label>
          )}
          {editingKey === 'gaokao_mode' && (
            <Radio.Group
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              className="ssf-mode-list"
              style={{ display: 'grid', gap: 10 }}
            >
              {MODES.map((item) => (
                <Radio key={item.value} value={item.value}>
                  <strong>{item.label}</strong>
                  <div style={{ color: 'var(--text-3)', fontSize: 12, marginTop: 2 }}>{item.note}</div>
                </Radio>
              ))}
            </Radio.Group>
          )}
          {editingKey === 'timetable_mode' && (
            <Radio.Group
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              className="ssf-mode-list"
              style={{ display: 'grid', gap: 10 }}
            >
              {TIMETABLE_MODES.map((item) => (
                <Radio key={item.value} value={item.value}>
                  <strong>{item.label}</strong>
                  <div style={{ color: 'var(--text-3)', fontSize: 12, marginTop: 2 }}>{item.note}</div>
                </Radio>
              ))}
            </Radio.Group>
          )}
          {editingKey === 'current_entry_year' && (
            <label className="ssf-label">
              {t(`${presentation.currentCohortTitle}（需存在于${presentation.cohortTabLabel}）`)}<Select
                value={editDraft}
                onChange={setEditDraft}
                options={academicYears.map((c) => ({
                  label: `${cohortDisplayName(c.entry_year, stage)}（${presentation.gradeNames[0]}：${academicYearAt(c.entry_year, 0)}）`,
                  value: c.entry_year,
                }))}
              />
            </label>
          )}
          {editingKey === 'current_academic_year' && (
            <label className="ssf-label">
              {t("当前学年")}<Select
                value={editDraft}
                onChange={setEditDraft}
                options={allAcademicYearOptions.map((v) => ({ label: t("{{p0}}学年", { p0: v }), value: v }))}
              />
            </label>
          )}
          {editingKey === 'current_term' && (
            <Radio.Group
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              options={[
                { label: t("上学期"), value: '1' },
                { label: t("下学期"), value: '2' },
              ]}
            />
          )}
        </div>
      </Modal>

      {/* 新建/编辑入学年级弹窗 */}
      <Modal
        title={editingEntryYear ? t(`编辑${presentation.cohortLabel}`) : t(`新建${presentation.cohortLabel}`)}
        open={cohortModalOpen}
        onOk={submitCohort}
        onCancel={() => setCohortModalOpen(false)}
        okText={editingEntryYear ? t("保存") : t("创建")}
        cancelText={t("取消")}
        width={460}
        destroyOnClose
      >
        <div className="ssf-form-modal">
          <label className="ssf-label">
            {t(`${presentation.cohortLabel}年份（${presentation.gradeNames[0]}入学年份）`)}<InputNumber
              min={2000}
              max={2100}
              value={cohortYear}
              onChange={(v) => setCohortYear(Number(v) || new Date().getFullYear())}
              style={{ width: '100%' }}
              addonAfter={t(stage === 'senior' ? "届" : "级")}
            />
          </label>
          <div className="ssf-cohort-preview">
            {stageGradeYears(cohortYear, stage).map((grade) => (
              <div key={grade.name}>
                <span>{t(grade.name)}</span>
                <strong>{grade.academicYear}</strong>
              </div>
            ))}
          </div>
        </div>
      </Modal>
    </div>
  )
}
