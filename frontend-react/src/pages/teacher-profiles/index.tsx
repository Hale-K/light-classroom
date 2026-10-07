import { useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Input,
  Modal,
  Progress,
  Select,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import type { TableProps } from 'antd'
import { schedulingApi, teacherProfilesApi } from '@/api'
import TableCard from '@/components/TableCard'
import ScheduleGrid from '@/components/ScheduleGrid'
import type {
  ScheduleEntry,
  SchedulingGridConfig,
  TeacherProfile,
  TeacherProfileClassSummary,
  TeacherProfileFiltersMeta,
  TeacherScheduleEntry,
} from '@/types'
import './index.css'

function mapTeacherScheduleEntries(items: TeacherScheduleEntry[]): ScheduleEntry[] {
  return (items || []).map((s) => ({
    id: s.id,
    class_id: s.class_id,
    weekday: s.weekday,
    period: s.period,
    subject_id: s.subject_id,
    teacher_id: s.teacher_id,
    room: s.room,
    academic_year: s.academic_year,
    term: s.term,
    week_parity: s.week_parity || 'all',
    teacher_name: s.teacher_name,
    subject_name: s.subject_name,
    class_name: s.class_name,
  }))
}

const WEEKDAY_COLORS: Record<string, string> = {
  语文: '#b91c1c',
  数学: '#1d4ed8',
  英语: '#0369a1',
  物理: '#4f46e5',
  化学: '#0f766e',
  生物: '#15803d',
  政治: '#7c2d12',
  历史: '#78350f',
  地理: '#334155',
  体育: '#65a30d',
}
const SUBJECT_ORDER = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '体育']

function subjectColor(name?: string) {
  if (!name) return '#94a3b8'
  return WEEKDAY_COLORS[name] ?? '#64748b'
}

function nameInitials(name: string) {
  if (!name) return '?'
  return name.slice(-2)
}

export default function TeacherProfilesView() {
  const { message } = App.useApp()

  const [loading, setLoading] = useState(false)
  const [filtersMeta, setFiltersMeta] = useState<TeacherProfileFiltersMeta | null>(null)
  const [metaLoading, setMetaLoading] = useState(false)

  // 筛选条件
  const [onlyHeadTeacher, setOnlyHeadTeacher] = useState(false)
  const [subjectId, setSubjectId] = useState<number | null>(null)
  const [gradeId, setGradeId] = useState<number | null>(null)
  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')

  const [academicYear, setAcademicYear] = useState<string>('')
  const [term, setTerm] = useState<string>('1')

  const [items, setItems] = useState<TeacherProfile[]>([])
  const [total, setTotal] = useState(0)
  /** 班级视角汇总（新增口径），若后端未返回则回退旧逻辑 */
  const [classSummary, setClassSummary] = useState<TeacherProfileClassSummary | null>(null)

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 教师个人课表弹窗（与排课页同一套 ScheduleGrid + 课位结构）
  const [scheduleVisible, setScheduleVisible] = useState(false)
  const [scheduleTeacher, setScheduleTeacher] = useState<TeacherProfile | null>(null)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleEntries, setScheduleEntries] = useState<ScheduleEntry[]>([])
  const [scheduleGrid, setScheduleGrid] = useState<SchedulingGridConfig | null>(null)

  const loadMeta = async () => {
    setMetaLoading(true)
    try {
      const meta = await teacherProfilesApi.filters()
      setFiltersMeta(meta)
      if (meta.defaults?.academic_year && !academicYear) setAcademicYear(meta.defaults.academic_year!)
      if (meta.defaults?.term) setTerm(meta.defaults.term)
    } finally {
      setMetaLoading(false)
    }
  }

  const loadList = async () => {
    setLoading(true)
    try {
      const res = await teacherProfilesApi.list({
        only_head_teacher: onlyHeadTeacher,
        subject_id: subjectId ?? null,
        grade_id: gradeId ?? null,
        academic_year: academicYear || null,
        term,
        keyword: appliedKeyword || null,
      })
      setItems(res.items || [])
      setTotal(res.total || 0)
      setClassSummary(res.class_summary ?? null)
      if (res.defaults) {
        if (res.defaults.academic_year && !academicYear) setAcademicYear(res.defaults.academic_year)
        if (res.defaults.term) setTerm(res.defaults.term)
      }
    } catch (e: any) {
      message.error(e?.message || '加载教师档案失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMeta()
  }, []) // eslint-disable-line

  useEffect(() => {
    // meta 拿到后才拉列表，保证筛选条件默认值带上
    if (filtersMeta) loadList()
    // eslint-disable-next-line
  }, [filtersMeta, onlyHeadTeacher, subjectId, gradeId, academicYear, term, appliedKeyword])

  const openSchedule = async (row: TeacherProfile) => {
    setScheduleTeacher(row)
    setScheduleVisible(true)
    setScheduleLoading(true)
    setScheduleEntries([])
    setScheduleGrid(null)
    const year = academicYear || filtersMeta?.defaults?.academic_year || ''
    try {
      const [result, grid] = await Promise.all([
        teacherProfilesApi.weeklySchedule(row.teacher_id, {
          academic_year: year || null,
          term,
        }),
        year
          ? schedulingApi.gridConfig({ academic_year: year, term }).catch(() => null)
          : Promise.resolve(null),
      ])
      setScheduleEntries(mapTeacherScheduleEntries(result.items || []))
      setScheduleGrid(grid)
    } catch (e: any) {
      message.error(e?.message || '加载教师课表失败')
    } finally {
      setScheduleLoading(false)
    }
  }

  const gradeOptions = useMemo(
    () => (filtersMeta?.grades ?? []).map((g) => ({ label: g.name, value: g.grade_id })),
    [filtersMeta],
  )
  const subjectOptions = useMemo(
    () => [...(filtersMeta?.subjects ?? [])]
      .sort((a, b) => {
        const left = SUBJECT_ORDER.indexOf(a.name)
        const right = SUBJECT_ORDER.indexOf(b.name)
        return (left < 0 ? SUBJECT_ORDER.length : left) - (right < 0 ? SUBJECT_ORDER.length : right)
      })
      .map((s) => ({ label: s.name, value: s.subject_id })),
    [filtersMeta],
  )

  const columns: TableProps<TeacherProfile>['columns'] = [
    {
      title: '老师',
      key: 'teacher',
      width: 230,
      fixed: 'left',
      render: (_, row) => {
        const color = row.is_head_teacher
          ? 'linear-gradient(135deg,#f59e0b,#ef4444)'
          : 'linear-gradient(135deg,#6366f1,#22c55e)'
        return (
          <div className="tp-identity">
            <div className="tp-avatar" style={{ background: color }}>
              {nameInitials(row.name)}
            </div>
            <div className="tp-identity-col">
              <div className="tp-name-row">
                <span className="tp-name">{row.name}</span>
                {row.is_head_teacher && <Tag color="orange" style={{ marginInlineStart: 6 }}>班主任</Tag>}
              </div>
              <div className="tp-phone">{row.phone || '—'}</div>
              {row.head_teacher_classes.length > 0 && (
                <div className="tp-ht-classes">
                  {row.head_teacher_classes.map((c) => (
                    <span key={c} className="tp-ht-class-tag">{c}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )
      },
    },
    {
      title: '老师职务',
      key: 'positions',
      width: 420,
      render: (_, row) => (
        <div className="tp-position-tags">
          {row.position_tags.length === 0 ? (
            <span style={{ color: 'var(--text-3)' }}>— 暂未任命</span>
          ) : (
            row.position_tags.map((tag) => (
              <Tooltip key={`${tag.organization_unit_id}-${tag.position_code}`} title={tag.display_text}>
                <Tag
                  closable
                  onClose={(e) => { e.preventDefault() }}
                  className="tp-position-tag"
                >
                  {tag.display_text}
                </Tag>
              </Tooltip>
            ))
          )}
        </div>
      ),
    },
    {
      title: '任教班级',
      key: 'teaching_classes',
      width: 360,
      render: (_, row) => (
        <div className="tp-class-list">
          {row.teaching_classes.length === 0 ? (
            <span style={{ color: 'var(--text-3)' }}>—</span>
          ) : (
            row.teaching_classes.map((tc, idx) => (
              <span key={`${tc.class_id}-${tc.subject_id}-${idx}`} className="tp-class-pill">
                <span
                  className="tp-class-subject-dot"
                  style={{ background: subjectColor(tc.subject_name) }}
                />
                <span className="tp-class-name">{tc.class_name}</span>
                <span className="tp-class-subject">{tc.subject_name}</span>
                <span className="tp-class-periods">周{tc.weekly_periods}</span>
                {tc.kind === 'walk' && <span className="tp-class-walk-tag">走班</span>}
              </span>
            ))
          )}
        </div>
      ),
    },
    {
      title: '当周排课比例',
      dataIndex: 'schedule_ratio',
      width: 220,
      render: (v: number, row) => {
        const pct = Math.round((v || 0) * 100)
        let status: 'success' | 'active' | 'exception' | undefined = undefined
        if (pct >= 95) status = 'success'
        else if (pct === 0) status = 'exception'
        else status = 'active'
        return (
          <div className="tp-ratio-cell">
            <Progress
              percent={pct}
              size="small"
              status={status}
              strokeColor={pct >= 95 ? '#16a34a' : pct === 0 ? '#ef4444' : '#6366f1'}
            />
            <div className="tp-ratio-foot">
              周课时目标 <b>{row.total_weekly_periods}</b> 节
            </div>
          </div>
        )
      },
    },
    {
      title: '本周已排课',
      dataIndex: 'scheduled_lessons_count',
      width: 140,
      render: (v: number, row) => (
        <div className="tp-lesson-count">
          <div className="tp-lesson-num" style={{ color: v >= row.total_weekly_periods ? '#16a34a' : '#1e293b' }}>
            {v}
          </div>
          <div className="tp-lesson-unit">节</div>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'op',
      width: 150,
      fixed: 'right',
      render: (_, row) => (
        <Button
          type="primary"
          size="small"
          className="tp-schedule-btn"
          onClick={() => openSchedule(row)}
        >
          查看课表
        </Button>
      ),
    },
  ]

  const pagedItems = useMemo(
    () => items.slice((page - 1) * pageSize, page * pageSize),
    [items, page, pageSize],
  )

  const summary = useMemo(() => {
    // 目标 / 已排均按课时管理折合周课时（含周六晚自习、单双周 0.5）
    let totalWeekly: number
    let totalSched: number
    let ratio: number
    let classCount = 0
    if (classSummary) {
      classCount = classSummary.class_count
      totalWeekly = classSummary.weekly_target
      totalSched = classSummary.scheduled_lessons
      ratio = Math.round(classSummary.completion_ratio)
    } else {
      totalWeekly = items.reduce((s, r) => s + r.total_weekly_periods, 0)
      totalSched = items.reduce((s, r) => s + r.scheduled_lessons_count, 0)
      ratio = totalWeekly ? Math.round((totalSched / totalWeekly) * 100) : 0
    }
    const ht = items.filter((i) => i.is_head_teacher).length
    return { total: items.length, ht, totalWeekly, totalSched, ratio, classCount }
  }, [items, classSummary])

  const schedulePeriods = scheduleGrid?.periods_per_day
    || Math.max(7, ...scheduleEntries.map((e) => e.period), 7)
  const scheduleDays = scheduleGrid?.days
    || Math.max(5, ...scheduleEntries.map((e) => e.weekday), 5)
  const showEvening = Boolean(scheduleGrid?.enable_evening)

  return (
    <div className="tp-page">
      <div className="chapter tp-header">
        <div>
          <h2 className="chapter-title">教师档案</h2>
          <p className="tp-header-desc">
            查看教师的组织岗位、任教班级与当周排课进度，可一键打开教师个人周课表。
          </p>
        </div>
        <div className="tp-header-meta chapter-actions">
          <div className="tp-stat">
            <span className="tp-stat-label">教师</span>
            <span className="tp-stat-num">{summary.total}</span>
            <span className="tp-stat-unit">人</span>
          </div>
          <div className="tp-stat tp-stat-warn">
            <span className="tp-stat-label">班主任</span>
            <span className="tp-stat-num">{summary.ht}</span>
            <span className="tp-stat-unit">人</span>
          </div>
          <div className="tp-stat tp-stat-info">
            <span className="tp-stat-label">目标周课</span>
            <span className="tp-stat-num">{summary.totalWeekly}</span>
            <span className="tp-stat-unit">节</span>
          </div>
          <div className="tp-stat tp-stat-ok">
            <span className="tp-stat-label">当周已排</span>
            <span className="tp-stat-num">{summary.totalSched}</span>
            <span className="tp-stat-unit">节 · {summary.ratio}%</span>
          </div>
        </div>
      </div>

      <TableCard>
        <div className="tp-filters">
          <Input
            allowClear
            placeholder="搜索老师姓名"
            style={{ width: 260 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => { setAppliedKeyword(keyword.trim()); setPage(1) }}
          />
          <Select
            allowClear
            placeholder="选择年级"
            style={{ width: 160 }}
            options={gradeOptions}
            value={gradeId}
            onChange={(v) => { setGradeId(v ?? null); setPage(1) }}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="任教科目"
            style={{ width: 150 }}
            options={subjectOptions}
            value={subjectId}
            onChange={(v) => { setSubjectId(v ?? null); setPage(1) }}
          />
          <div className="tp-filter-ht-switch">
            <span>仅看班主任</span>
            <Switch
              size="small"
              checked={onlyHeadTeacher}
              onChange={(v) => { setOnlyHeadTeacher(v); setPage(1) }}
            />
          </div>
          <div className="tp-filter-actions">
            <Button
              type="primary"
              onClick={() => { setAppliedKeyword(keyword.trim()); setPage(1); loadList() }}
            >
              查询
            </Button>
            <Button
              onClick={() => {
                setKeyword('')
                setAppliedKeyword('')
                setOnlyHeadTeacher(false)
                setSubjectId(null)
                setGradeId(null)
                setTerm(filtersMeta?.defaults?.term || '1')
                setPage(1)
              }}
            >
              重置
            </Button>
          </div>
        </div>

        <div className="tp-summary-bar">
          <Tag color="purple">共 {total} 位教师</Tag>
          <Tag color="#db2777">班主任 {summary.ht} 人</Tag>
          <Tag color="#0369a1">周目标 {summary.totalWeekly} 节</Tag>
          <Tag color="#16a34a">已排 {summary.totalSched} 节</Tag>
          <Tag color={summary.ratio >= 95 ? 'success' : 'warning'}>
            完成度 {summary.ratio}%
          </Tag>
        </div>

        <Table<TeacherProfile>
          rowKey={(r) => r.teacher_id}
          columns={columns}
          loading={loading || metaLoading}
          dataSource={pagedItems}
          scroll={{ x: 1580 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showQuickJumper: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            showTotal: (t) => `共 ${t} 条记录`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
        />
      </TableCard>

      <Modal
        className="tp-schedule-modal"
        title={
          <div className="tp-modal-title">
            <span className="tp-modal-teacher-name">
              {scheduleTeacher?.name} 的周课表
            </span>
            {scheduleTeacher?.is_head_teacher && (
              <Tag color="orange">班主任</Tag>
            )}
            {scheduleTeacher?.position_tags?.slice(0, 2).map((t) => (
              <Tag key={t.display_text} style={{ background: 'var(--bg-2)', color: 'var(--text-2)' }}>
                {t.display_text}
              </Tag>
            ))}
          </div>
        }
        open={scheduleVisible}
        onCancel={() => setScheduleVisible(false)}
        footer={null}
        width={1280}
        destroyOnClose
        centered
      >
        {scheduleLoading ? (
          <div className="tp-schedule-empty">正在加载课表…</div>
        ) : scheduleEntries.length === 0 ? (
          <div className="tp-schedule-empty">暂无当周课表，请先生成排课。</div>
        ) : (
          <div className="tp-schedule-surface">
            <div className="tp-schedule-overview">
              <div className="tp-schedule-overview-copy">
                <span className="tp-schedule-overview-label">WEEKLY RHYTHM</span>
                <strong>教师授课节奏</strong>
                <span>
                  {academicYear || '当前学年'} · 第{term}学期
                  {showEvening ? ' · 含晚自习' : ''}
                  {scheduleDays >= 6 ? ' · 含周六单双周' : ''}
                </span>
              </div>
              <div className="tp-schedule-legend" aria-label="学科颜色图例">
                <span><i className="tp-legend-swatch language" />语言</span>
                <span><i className="tp-legend-swatch math" />数学</span>
                <span><i className="tp-legend-swatch science" />理科</span>
                <span><i className="tp-legend-swatch humanities" />文科</span>
                <span><i className="tp-legend-swatch activity" />活动</span>
              </div>
            </div>
            <ScheduleGrid
              entries={scheduleEntries}
              periods={schedulePeriods}
              days={scheduleDays}
              dailyPeriods={scheduleGrid?.daily_periods}
              showEvening={showEvening}
              eveningStartPeriod={scheduleGrid?.evening_start_period}
              showClassName
            />
          </div>
        )}
      </Modal>
    </div>
  )
}
