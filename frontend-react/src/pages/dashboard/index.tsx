import { useEffect, useMemo, useState } from 'react'
import { App, Spin } from 'antd'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { dashboardApi, schedulingApi } from '@/api'
import Icon from '@/components/Icon'
import { useAuthStore } from '@/store/auth'
import type { ScheduleVersionSummary, SchedulingResources } from '@/types'
import TeacherWorkbench from './TeacherWorkbench'
import './index.css'

type WorkbenchRole = 'academic' | 'teacher'

function getWorkbenchRole(user: { role?: string; roles?: string[] } | null): WorkbenchRole {
  if (user?.role === 'director' || user?.roles?.includes('academic_director') || user?.roles?.includes('school_admin')) {
    return 'academic'
  }
  return 'teacher'
}

interface WorkbenchAction {
  title: string
  detail: string
  path: string
  icon: string
  tone: 'blue' | 'amber' | 'green' | 'violet'
}

const academicActions: WorkbenchAction[] = [
  { title: '排课管理', detail: '检查任教关系并生成课表', path: '/scheduling', icon: 'calendar', tone: 'blue' },
  { title: '排考管理', detail: '创建考场并安排考试人员', path: '/exam-rooms', icon: 'file-text', tone: 'amber' },
  { title: '行政分班', detail: '按已分配资源生成班级', path: '/classes', icon: 'users', tone: 'violet' },
  { title: '空间资源', detail: '查看校区、楼宇与场室', path: '/campus-buildings', icon: 'building', tone: 'green' },
]

function Metric({ icon, label, value, suffix, hint }: { icon: string; label: string; value: number | string; suffix?: string; hint: string }) {
  return (
    <div className="wb-metric">
      <span className="wb-metric-label"><i><Icon name={icon} size={15} /></i>{label}</span>
      <strong>{value}<small>{suffix}</small></strong>
      <em>{hint}</em>
    </div>
  )
}

function ActionCard({ action, onClick }: { action: WorkbenchAction; onClick: () => void }) {
  return (
    <button type="button" className="wb-action-card" onClick={onClick}>
      <span className={`wb-action-icon ${action.tone}`}><Icon name={action.icon} size={19} /></span>
      <span className="wb-action-copy"><b>{action.title}</b><small>{action.detail}</small></span>
      <Icon name="arrow-right" size={15} className="wb-arrow" />
    </button>
  )
}

function AcademicWorkbench() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const schoolCode = useAuthStore((state) => state.schoolCode)
  const [loading, setLoading] = useState(true)
  const [scheduleResources, setScheduleResources] = useState<SchedulingResources>({
    teachers: [], subjects: [], classes: [], assignments: [], teaching_track_subject_ids: [],
  })
  const [scheduleVersions, setScheduleVersions] = useState<ScheduleVersionSummary[]>([])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        await dashboardApi.summary()
        const [resources, versions] = await Promise.all([
          schedulingApi.resources(),
          schedulingApi.listVersions(),
        ])
        if (cancelled) return
        setScheduleResources(resources)
        setScheduleVersions(versions)
      } catch {
        if (!cancelled) message.error('加载工作台数据失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [message])

  const activeAcademicYear = dayjs().month() >= 7
    ? `${dayjs().year()}-${dayjs().year() + 1}`
    : `${dayjs().year() - 1}-${dayjs().year()}`
  const activeTerm = dayjs().month() >= 1 && dayjs().month() < 7 ? '2' : '1'
  const activeAssignments = useMemo(
    () => scheduleResources.assignments.filter(
      (item) => item.academic_year === activeAcademicYear && item.term === activeTerm,
    ),
    [activeAcademicYear, activeTerm, scheduleResources.assignments],
  )
  const scheduledVersion = useMemo(
    () => scheduleVersions.find(
      (item) => item.academic_year === activeAcademicYear && item.term === activeTerm,
    ),
    [activeAcademicYear, activeTerm, scheduleVersions],
  )
  const plannedLessons = useMemo(
    () => Math.round(activeAssignments.reduce((total, item) => total + (item.weekly_periods || 0), 0) * 10) / 10,
    [activeAssignments],
  )
  const scheduledLessons = scheduledVersion?.lesson_count || 0
  const pendingLessons = Math.max(0, Math.round((plannedLessons - scheduledLessons) * 10) / 10)
  const scheduleCoverage = plannedLessons > 0
    ? Math.min(100, Math.round((scheduledLessons / plannedLessons) * 100))
    : 0
  const scheduleClassCount = useMemo(
    () => new Set(activeAssignments.map((item) => item.class_id)).size,
    [activeAssignments],
  )
  const unboundTeacherCount = useMemo(
    () => activeAssignments.filter((item) => item.teacher_id === null).length,
    [activeAssignments],
  )

  return (
    <div className="wb-page">
      <Spin spinning={loading}>
        <header className="wb-header">
          <div>
            <span className="wb-kicker"><i />教务工作台 · {schoolCode || '当前学校'}</span>
            <h1>本学期教学安排</h1>
            <p>统一查看排课、排考与班级资源。</p>
          </div>
          <div className="wb-header-meta">
            <span className="wb-sync"><i />数据已同步</span>
            <span>{dayjs().format('YYYY年M月D日')}</span>
            <b>{dayjs().format('dddd')}</b>
          </div>
        </header>

        <section className="wb-metrics" aria-label="工作台统计">
          <Metric icon="calendar" label="计划课时" value={plannedLessons} suffix="节" hint="本学期配置" />
          <Metric icon="circle-check" label="已生成" value={scheduledLessons} suffix="节" hint="当前课表版本" />
          <Metric icon="alert-triangle" label="待排课时" value={pendingLessons} suffix="节" hint="需要处理" />
          <Metric icon="users" label="任教关系" value={activeAssignments.length} suffix="条" hint="当前学期" />
        </section>

        <section className="wb-schedule-overview" aria-label="排课进度">
          <div className="wb-overview-head">
            <div>
              <span className="wb-section-label">排课进度</span>
              <h2>{scheduledVersion ? `第 ${scheduledVersion.version_id} 版课表` : '尚未生成课表'}</h2>
            </div>
            <strong>{scheduleCoverage}%</strong>
          </div>
          <div className="wb-overview-track"><i style={{ width: `${scheduleCoverage}%` }} /></div>
          <div className="wb-overview-meta">
            <span>已生成 {scheduledLessons} 节</span>
            <span>共计划 {plannedLessons} 节</span>
            <span>{pendingLessons > 0 ? `还差 ${pendingLessons} 节` : '课时已覆盖'}</span>
          </div>
          <div className="wb-resource-strip">
            <span><i className="blue" />班级范围 <b>{scheduleClassCount}</b></span>
            <span><i className="violet" />教师资源 <b>{scheduleResources.teachers.length}</b></span>
            <span><i className="green" />任教关系 <b>{activeAssignments.length}</b></span>
          </div>
        </section>

        <section className="wb-focus-card" aria-label="下一步操作">
          <span className="wb-focus-mark"><Icon name="calendar" size={24} /></span>
          <div className="wb-focus-copy">
            <span className="wb-section-label">现在开始</span>
            <h2>{pendingLessons > 0 ? `还有 ${pendingLessons} 节课待排` : '课表已生成，继续校验冲突'}</h2>
            <p>
              {unboundTeacherCount > 0
                ? `发现 ${unboundTeacherCount} 条任教关系尚未绑定教师。`
                : '检查任教关系、课时和教室后生成最终课表。'}
            </p>
          </div>
          <button type="button" className="wb-focus-action" onClick={() => navigate('/scheduling')}>
            {pendingLessons > 0 ? '处理待排' : '进入排课'} <Icon name="arrow-right" size={14} />
          </button>
        </section>

        <section className="wb-section">
          <div className="wb-section-head">
            <div>
              <span className="wb-section-label">功能导航</span>
              <h2>常用功能</h2>
            </div>
          </div>
          <div className="wb-action-grid">
            {academicActions.map((action) => (
              <ActionCard key={action.title} action={action} onClick={() => navigate(action.path)} />
            ))}
          </div>
        </section>

      </Spin>
    </div>
  )
}

export default function Dashboard() {
  const user = useAuthStore((state) => state.user)
  const role = getWorkbenchRole(user)
  if (role === 'teacher') return <TeacherWorkbench />
  return <AcademicWorkbench />
}
