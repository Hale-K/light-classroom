import { useEffect, useMemo, useState } from 'react'
import { App, Button, InputNumber, Modal, Pagination, Radio, Select, Space, Tabs, Tag } from 'antd'
import { authApi, type AcademicYearEntry, type AcademicYearRolloverPreview, type SchoolSettings } from '@/api'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import './school-settings-form.css'

type GaokaoMode = '3+1+2' | '3+3' | 'traditional'
type CohortStatus = AcademicYearEntry['status']
type BasicKey = 'province' | 'gaokao_mode' | 'current_entry_year' | 'current_academic_year' | 'current_term' | 'head_teacher_max_lead'

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
}

export default function SchoolSettingsForm({ onSaved }: Props) {
  const { message, modal } = App.useApp()
  const [settings, setSettings] = useState<SchoolSettings | null>(null)
  const [academicYears, setAcademicYears] = useState<AcademicYearEntry[]>([])
  const [currentEntryYear, setCurrentEntryYear] = useState<number>()
  const [currentAcademicYear, setCurrentAcademicYear] = useState<string>()
  const [currentTerm, setCurrentTerm] = useState<'1' | '2'>('1')
  const [activeTab, setActiveTab] = useState<'basic' | 'cohorts'>('basic')

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

  const openRollover = async () => {
    if (currentEntryYear === undefined) return
    setRolloverOpen(true)
    setRolloverLoading(true)
    try {
      setRolloverPreview(await authApi.previewAcademicYearRollover(currentEntryYear))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '学年滚动预览失败')
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
      message.success(`已进入 ${result.current_academic_year}，晋级 ${result.promoted_student_count} 名学生`)
      onSaved?.()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '学年滚动失败')
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
      .catch((e) => message.error(e instanceof Error ? e.message : '学校信息加载失败'))
  }, [message])

  /** 统一把当前届次/学年/学期提交给后端，保持前后端同步 */
  const persistCurrent = async (
    nextYears: AcademicYearEntry[] = academicYears,
    entryYear: number | undefined = currentEntryYear,
    academicYear: string | undefined = currentAcademicYear,
    term: '1' | '2' = currentTerm,
  ) => {
    const result = await authApi.saveAcademicYears(
      nextYears.map((item) => ({ entry_year: item.entry_year, status: item.status })),
      entryYear ?? null,
      academicYear ?? null,
      term,
    )
    setAcademicYears(result.years)
    setCurrentEntryYear(result.current_entry_year ?? undefined)
    setCurrentAcademicYear(result.current_academic_year ?? undefined)
    setCurrentTerm(result.current_term ?? '1')
    return result
  }

  /** 基础配置 5 条规则数据 */
  const basicRules = useMemo(() => {
    const curCohort = academicYears.find((item) => item.entry_year === currentEntryYear)
    return [
      {
        key: 'province' as BasicKey,
        icoColor: 'blue',
        icoName: 'building',
        title: '学校所在省份',
        subtitle: settings?.name || '学校',
        chipColor: 'blue',
        chipLabel: settings?.province || '未设置',
        modeTag: '',
        desc: settings?.province
          ? `当前省份为「${settings.province}」，会作为选科方案、考务信息的默认省域。`
          : '尚未配置学校所在省份，请点击“编辑”选择。',
      },
      {
        key: 'gaokao_mode' as BasicKey,
        icoColor: 'purple',
        icoName: 'book',
        title: '默认高考模式',
        subtitle: settings?.code || '租户默认',
        chipColor: 'purple',
        chipLabel: (MODES.find((item) => item.value === settings?.gaokao_mode)?.label) || '未设置',
        modeTag: MODES.find((item) => item.value === settings?.gaokao_mode)?.note || '',
        desc: MODES.find((item) => item.value === settings?.gaokao_mode)
          ? `全校默认采用「${MODES.find((item) => item.value === settings?.gaokao_mode)?.label}」模式，新建届别自动继承，已建立的届别可独立修改。`
          : '尚未指定高考模式，请点击“编辑”选择。',
      },
      {
        key: 'current_entry_year' as BasicKey,
        icoColor: 'green',
        icoName: 'school' as any,
        title: '当前高一届别',
        subtitle: curCohort ? `${curCohort.grade_years['高一']} 学年入学` : '届次列表为空',
        chipColor: 'green',
        chipLabel: curCohort?.cohort_label || '未设置',
        modeTag: curCohort ? `高一：${curCohort.grade_years['高一']}` : '',
        desc: curCohort
          ? `新生入学届别：${curCohort.cohort_label}，对应高一学年 ${curCohort.grade_years['高一']}，高二 ${curCohort.grade_years['高二']}，高三 ${curCohort.grade_years['高三']}。`
          : '尚未设置当前届别，请到“届次管理”Tab 新建届别并设为当前。',
      },
      {
        key: 'current_academic_year' as BasicKey,
        icoColor: 'orange',
        icoName: 'calendar',
        title: '当前学年',
        subtitle: '排课 / 选科的默认学年',
        chipColor: 'orange',
        chipLabel: currentAcademicYear || '未设置',
        modeTag: '',
        desc: currentAcademicYear
          ? `所有学年相关模块默认显示 ${currentAcademicYear}学年 的数据。`
          : '尚未指定当前学年，请先在届次管理中建立届别。',
      },
      {
        key: 'current_term' as BasicKey,
        icoColor: 'pink',
        icoName: 'circle-check',
        title: '当前学期',
        subtitle: '影响排课、考试、考勤的学期维度',
        chipColor: 'pink',
        chipLabel: currentTerm === '1' ? '上学期' : '下学期',
        modeTag: currentTerm === '1' ? '第 1 学期' : '第 2 学期',
        desc: `当前处于第 ${currentTerm === '1' ? '一' : '二'} 学期，切换后各学年相关模块的默认学期随之更新。`,
      },
    ]
  }, [settings, academicYears, currentEntryYear, currentAcademicYear, currentTerm])

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
      if (editingKey === 'province' || editingKey === 'gaokao_mode') {
        const patch: any = {}
        if (editingKey === 'province') patch.province = editDraft as string
        if (editingKey === 'gaokao_mode') patch.gaokao_mode = editDraft as GaokaoMode
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
          year = row ? row.grade_years['高一'] : year
        } else if (editingKey === 'current_academic_year') {
          year = String(editDraft)
        } else if (editingKey === 'current_term') {
          term = editDraft as '1' | '2'
        }
        await persistCurrent(years, entry, year, term)
      }
      message.success('配置已更新')
      setEditingKey(null)
      onSaved?.()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
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
      message.warning('请填写届别年份')
      return
    }
    const exists = academicYears.some((item) => item.entry_year === cohortYear)
    if (!editingEntryYear && exists) {
      message.warning(`${cohortYear}届已经存在`)
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
      message.success(editingEntryYear ? '届别已更新' : '届别已创建')
      setCohortModalOpen(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '届别保存失败')
    }
  }

  const setAsCurrentCohort = async (item: AcademicYearEntry) => {
    try {
      await persistCurrent(academicYears, item.entry_year, `${item.entry_year}-${item.entry_year + 1}`, currentTerm)
      message.success(`已切换到 ${item.cohort_label} · ${item.entry_year}-${item.entry_year + 1}学年`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '切换失败')
    }
  }

  const toggleCohortStatus = async (item: AcademicYearEntry) => {
    const nextStatus: CohortStatus = item.status === 'active' ? 'inactive' : 'active'
    const nextYears = academicYears.map((row) =>
      row.entry_year === item.entry_year ? { ...row, status: nextStatus } : row,
    )
    try {
      await persistCurrent(nextYears)
      message.success(`${item.cohort_label} 已${nextStatus === 'active' ? '启用' : '归档'}`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '操作失败')
    }
  }

  const removeCohort = async (item: AcademicYearEntry) => {
    if (currentEntryYear === item.entry_year) {
      message.warning('当前届别无法删除，请先切换到其他届别')
      return
    }
    modal.confirm({
      title: `确认删除 ${item.cohort_label}？`,
      content: '删除后，该届别与选科、排班相关的历史配置将不再引用，操作不可恢复。',
      okType: 'danger',
      onOk: async () => {
        const nextYears = academicYears.filter((row) => row.entry_year !== item.entry_year)
        await persistCurrent(nextYears)
        message.success('届别已删除')
      },
    })
  }

  const allAcademicYearOptions = useMemo(() => {
    const set = new Set<string>()
    academicYears.forEach((item) => Object.values(item.grade_years).forEach((v) => set.add(v)))
    return Array.from(set).sort().reverse()
  }, [academicYears])

  const [cohortPage, setCohortPage] = useState(1)
  const COHORT_PAGE_SIZE = 6
  const paginatedCohorts = useMemo(() => {
    const start = (cohortPage - 1) * COHORT_PAGE_SIZE
    return academicYears.slice(start, start + COHORT_PAGE_SIZE)
  }, [academicYears, cohortPage])

  if (!settings) return null

  return (
    <div className="ssf-form-v2">
      {/* 顶部：大标题 + 说明 */}
      <div className="ssf-page-head">
        <div className="ssf-page-head-title">
          <h1>系统设置</h1>
          <p>按规则管理学校的学年届次与默认高考模式；配置项一行一条，不再凌乱摆放。</p>
        </div>
      </div>

      {/* 当前生效概览卡 */}
      <div className="ssf-brief">
        <div className="ssf-brief-card active">
          <span>当前届别</span>
          <strong>{academicYears.find((c) => c.entry_year === currentEntryYear)?.cohort_label || '未设置'}</strong>
          <small>{currentEntryYear ? `高一学年：${currentEntryYear}-${currentEntryYear + 1}` : '请新建届别'}</small>
        </div>
        <div className="ssf-brief-card">
          <span>当前学年</span>
          <strong>{currentAcademicYear || '未设置'}</strong>
          <small>排课 / 选科默认学年</small>
        </div>
        <div className="ssf-brief-card">
          <span>当前学期</span>
          <strong>第{currentTerm === '1' ? '一' : '二'}学期</strong>
          <small>高考模式：{MODES.find((m) => m.value === settings.gaokao_mode)?.label}</small>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        className="ssf-tabs"
        activeKey={activeTab}
        onChange={(k: string) => setActiveTab(k as 'basic' | 'cohorts')}
        items={[
          {
            key: 'basic',
            label: '基础配置',
            children: (
              <div className="ssf-rule-card">
                <div className="ssf-rule-head">
                  <div>配置项</div>
                  <div>当前值</div>
                  <div>标记</div>
                  <div>说明</div>
                  <div style={{ textAlign: 'right' }}>操作</div>
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
                            <Tag color="blue">当前</Tag>
                          )}
                        </strong>
                        <small>{rule.subtitle}</small>
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
                      <Button type="link" size="small" onClick={() => openEditBasic(rule.key)}>编辑</Button>
                    </div>
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'cohorts',
            label: '届次管理',
            children: (
              <div className="ssf-rule-card">
                <div className="ssf-rule-subnav">
                  <div>
                    <h2>学年届别清单</h2>
                    <p>每创建一个届别，系统会按高一→高三生成对应三年的年级名称，用于排课 / 学生列表。</p>
                  </div>
                  <Space>
                    <Button onClick={openRollover} disabled={currentEntryYear === undefined}>进入下一学年</Button>
                    <Button type="primary" size="large" icon={<Icon name="plus" size={14} />} onClick={openNewCohort}>新建届别</Button>
                  </Space>
                </div>
                <div className="ssf-rule-head">
                  <div>届别名称</div>
                  <div>高三学年</div>
                  <div>状态</div>
                  <div>说明</div>
                  <div style={{ textAlign: 'right' }}>操作</div>
                </div>
                {paginatedCohorts.length === 0 ? (
                  <div className="ssf-empty">
                    <EmptyState
                      height={180}
                      title="暂无届别"
                      desc="点击上方「新建届别」创建学年届别"
                    />
                  </div>
                ) : (
                  paginatedCohorts.map((record) => (
                    <div key={record.entry_year} className="ssf-rule-row">
                      <div className="ssf-rule-name">
                      <span className={`ssf-rule-ico ${currentEntryYear === record.entry_year ? 'green' : 'purple'}`}>
                        <Icon name="school" size={16} />
                      </span>
                        <span className="ssf-rule-text">
                          <strong>
                            {record.cohort_label}
                            {currentEntryYear === record.entry_year && (
                              <Tag color="blue">默认</Tag>
                            )}
                          </strong>
                          <small>高一：{record.grade_years['高一']}</small>
                        </span>
                      </div>
                      <div>
                        <span className="ssf-rule-chip purple">{record.grade_years['高三']}</span>
                      </div>
                      <div>
                        <Tag color={record.status === 'active' ? 'green' : 'default'}>
                          {STATUS_LABEL[record.status]}
                        </Tag>
                      </div>
                      <div className="ssf-rule-desc">
                        {record.cohort_label}入学 → 高一 {record.grade_years['高一']} → 高三 {record.grade_years['高三']} 毕业
                      </div>
                      <div className="ssf-rule-actions">
                        <Space size={2}>
                          <Button
                            type="text"
                            size="small"
                            disabled={currentEntryYear === record.entry_year}
                            title="设为当前届别"
                            onClick={() => setAsCurrentCohort(record)}
                          >
                            <Icon name="star" size={14} />
                          </Button>
                          <Button
                            type="text"
                            size="small"
                            title="编辑"
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
                  ))
                )}
                {academicYears.length > 0 && (
                  <div className="ssf-pagination">
                    共 {academicYears.length} 个届别
                    <Pagination
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
          },
        ]}
      />

      <Modal
        title="进入下一学年"
        open={rolloverOpen}
        onCancel={() => setRolloverOpen(false)}
        footer={rolloverPreview && !rolloverPreview.already_done ? [
          <Button key="cancel" onClick={() => setRolloverOpen(false)}>取消</Button>,
          <Button key="confirm" type="primary" loading={rolloverLoading} onClick={commitRollover}>确认滚动</Button>,
        ] : [<Button key="close" onClick={() => setRolloverOpen(false)}>关闭</Button>]}
        width={640}
        centered
        destroyOnClose
      >
        {rolloverLoading && !rolloverPreview ? <div style={{ padding: 36, textAlign: 'center' }}>正在计算滚动预览…</div> : rolloverPreview && (
          <div className="ssf-form-modal">
            <div className="ssf-brief" style={{ gridTemplateColumns: '1fr 1fr', margin: 0 }}>
              <div className="ssf-brief-card"><span>当前学年</span><strong>{rolloverPreview.source_academic_year}</strong><small>{rolloverPreview.source_cohort_label}</small></div>
              <div className="ssf-brief-card active"><span>滚动后</span><strong>{rolloverPreview.target_academic_year}</strong><small>{rolloverPreview.target_cohort_label}</small></div>
            </div>
            <div className="ssf-rule-card" style={{ marginTop: 16 }}>
              <div className="ssf-rule-row"><strong>待处理学生</strong><span>{rolloverPreview.student_count} 人</span></div>
              <div className="ssf-rule-row"><strong>高一 → 高二</strong><span>{rolloverPreview.promote_high_one_classes} 个班</span></div>
              <div className="ssf-rule-row"><strong>高二 → 高三</strong><span>{rolloverPreview.promote_high_two_classes} 个班</span></div>
              <div className="ssf-rule-row"><strong>高三毕业</strong><span>{rolloverPreview.graduate_high_three_classes} 个班</span></div>
            </div>
            {rolloverPreview.warnings.map((warning) => <div key={warning} style={{ color: '#b7791f', marginTop: 14 }}>{warning}</div>)}
            {rolloverPreview.already_done && <div style={{ color: '#b42318', marginTop: 14 }}>该届别已经执行过滚动，不能重复执行。</div>}
          </div>
        )}
      </Modal>

      {/* 基础配置编辑弹窗 */}
      <Modal
        title={`编辑：${basicRules.find((r) => r.key === editingKey)?.title || ''}`}
        open={editingKey !== null}
        onOk={submitBasicEdit}
        onCancel={() => setEditingKey(null)}
        okText="保存"
        cancelText="取消"
        width={460}
        destroyOnClose
      >
        <div className="ssf-form-modal">
          {editingKey === 'province' && (
            <label className="ssf-label">
              学校所在省份
              <Select
                showSearch
                value={editDraft}
                onChange={setEditDraft}
                placeholder="选择省份"
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
          {editingKey === 'current_entry_year' && (
            <label className="ssf-label">
              当前高一届别（需存在于届次列表）
              <Select
                value={editDraft}
                onChange={setEditDraft}
                options={academicYears.map((c) => ({
                  label: `${c.cohort_label}（高一：${c.grade_years['高一']}）`,
                  value: c.entry_year,
                }))}
              />
            </label>
          )}
          {editingKey === 'current_academic_year' && (
            <label className="ssf-label">
              当前学年
              <Select
                value={editDraft}
                onChange={setEditDraft}
                options={allAcademicYearOptions.map((v) => ({ label: `${v}学年`, value: v }))}
              />
            </label>
          )}
          {editingKey === 'current_term' && (
            <Radio.Group
              value={editDraft}
              onChange={(e) => setEditDraft(e.target.value)}
              options={[
                { label: '上学期', value: '1' },
                { label: '下学期', value: '2' },
              ]}
            />
          )}
        </div>
      </Modal>

      {/* 新建/编辑届别弹窗 */}
      <Modal
        title={editingEntryYear ? '编辑届别' : '新建届别'}
        open={cohortModalOpen}
        onOk={submitCohort}
        onCancel={() => setCohortModalOpen(false)}
        okText={editingEntryYear ? '保存' : '创建'}
        cancelText="取消"
        width={460}
        destroyOnClose
      >
        <div className="ssf-form-modal">
          <label className="ssf-label">
            届别年份（高一入学年份）
            <InputNumber
              min={2000}
              max={2100}
              value={cohortYear}
              onChange={(v) => setCohortYear(Number(v) || new Date().getFullYear())}
              style={{ width: '100%' }}
              addonAfter="届"
            />
          </label>
          <div className="ssf-cohort-preview">
            <div>
              <span>高一</span>
              <strong>{cohortYear}-{cohortYear + 1}</strong>
            </div>
            <div>
              <span>高二</span>
              <strong>{cohortYear + 1}-{cohortYear + 2}</strong>
            </div>
            <div>
              <span>高三</span>
              <strong>{cohortYear + 2}-{cohortYear + 3}</strong>
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}
