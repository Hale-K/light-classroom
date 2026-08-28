import { useEffect, useMemo, useState } from 'react'
import { App, Button, Spin } from 'antd'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { dashboardApi, orgApi } from '@/api'
import Icon from '@/components/Icon'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import { EXAM_STATUS_DICT, EXAM_TYPE_DICT, SCAN_BATCH_STATUS_DICT } from '@/types/dict'
import { useAuthStore } from '@/store/auth'
import type { Exam, ScanBatch } from '@/types'
import './index.css'

type WorkbenchRole = 'academic' | 'headTeacher' | 'teacher'
interface WorkbenchAction { title: string; detail: string; path: string; icon: string; tone: 'blue' | 'amber' | 'green' | 'violet' }

function getWorkbenchRole(user: { role?: string; roles?: string[] } | null): WorkbenchRole {
  if (user?.role === 'director' || user?.roles?.includes('academic_director')) return 'academic'
  if (user?.roles?.includes('head_teacher')) return 'headTeacher'
  return 'teacher'
}

const roleCopy: Record<WorkbenchRole, { label: string; title: string; subtitle: string }> = {
  academic: { label: '教务工作台', title: '把本学期的教学安排推进下去', subtitle: '从班级、任教关系到排课与考试，按业务流程集中处理。' },
  headTeacher: { label: '班主任工作台', title: '先看本班今天要处理的事', subtitle: '班级学生、座位、考试和日常管理都从这里进入。' },
  teacher: { label: '教师工作台', title: '今天的教学安排，一眼就能找到', subtitle: '查看我的课表、任教班级与需要参与的考试工作。' },
}

const actions: Record<WorkbenchRole, WorkbenchAction[]> = {
  academic: [
    { title: '排课管理', detail: '检查任教关系并生成课表', path: '/scheduling', icon: 'calendar', tone: 'blue' },
    { title: '排考管理', detail: '创建考场并安排考试人员', path: '/exam-rooms', icon: 'file-text', tone: 'amber' },
    { title: '行政分班', detail: '按已分配资源生成班级', path: '/classes', icon: 'users', tone: 'violet' },
    { title: '空间资源', detail: '查看校区、楼宇与场室', path: '/campus-buildings', icon: 'building', tone: 'green' },
  ],
  headTeacher: [
    { title: '班级名单', detail: '查看学生与班级信息', path: '/classes', icon: 'users', tone: 'blue' },
    { title: '班级排座', detail: '生成或调整本班座位', path: '/seating', icon: 'grid', tone: 'violet' },
    { title: '考试安排', detail: '查看本班考试与考场', path: '/exam-calendar', icon: 'calendar', tone: 'amber' },
    { title: '查看课表', detail: '进入班级日期课表', path: '/scheduling', icon: 'book', tone: 'green' },
  ],
  teacher: [
    { title: '我的课表', detail: '查看本周授课安排', path: '/scheduling', icon: 'calendar', tone: 'blue' },
    { title: '任教班级', detail: '查看我的授课范围', path: '/teacher-profiles', icon: 'users', tone: 'violet' },
    { title: '监考安排', detail: '查看需要参加的考试', path: '/exam-invigilators', icon: 'file-text', tone: 'amber' },
    { title: '考试阅卷', detail: '处理待批改的答卷', path: '/exams', icon: 'edit', tone: 'green' },
  ],
}

function Metric({ icon, label, value, suffix, hint }: { icon: string; label: string; value: number | string; suffix?: string; hint: string }) {
  return <div className="wb-metric"><span className="wb-metric-label"><i><Icon name={icon} size={15} /></i>{label}</span><strong>{value}<small>{suffix}</small></strong><em>{hint}</em></div>
}

function ActionCard({ action, onClick }: { action: WorkbenchAction; onClick: () => void }) {
  return <button type="button" className="wb-action-card" onClick={onClick}><span className={`wb-action-icon ${action.tone}`}><Icon name={action.icon} size={19} /></span><span className="wb-action-copy"><b>{action.title}</b><small>{action.detail}</small></span><Icon name="arrow-right" size={15} className="wb-arrow" /></button>
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const user = useAuthStore((state) => state.user)
  const schoolCode = useAuthStore((state) => state.schoolCode)
  const role = getWorkbenchRole(user)
  const copy = roleCopy[role]
  const [loading, setLoading] = useState(true)
  const [exams, setExams] = useState<Exam[]>([])
  const [batches, setBatches] = useState<ScanBatch[]>([])
  const [studentTotal, setStudentTotal] = useState(0)
  const [paperCount, setPaperCount] = useState(0)
  const [gradedTotal, setGradedTotal] = useState(0)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const [summary, students] = await Promise.all([dashboardApi.summary(), orgApi.studentCount()])
        if (cancelled) return
        setExams(summary.exams); setBatches(summary.batches); setStudentTotal(students.total)
        setPaperCount(summary.paper_count); setGradedTotal(summary.graded_total)
      } catch { if (!cancelled) message.error('加载工作台数据失败') } finally { if (!cancelled) setLoading(false) }
    })()
    return () => { cancelled = true }
  }, [message])

  const ongoingExams = useMemo(() => exams.filter((exam) => exam.status === 'ongoing').length, [exams])
  const pendingBatches = useMemo(() => batches.filter((batch) => batch.status && batch.status !== 'confirmed').length, [batches])
  const visualRows = role === 'academic' ? [
    { label: '考试安排', value: exams.length, note: `${ongoingExams} 场进行中`, icon: 'calendar', tone: 'blue', width: exams.length ? Math.min(100, Math.max(18, ongoingExams / exams.length * 100)) : 0 },
    { label: '扫描进卷', value: batches.length, note: `${pendingBatches} 批待处理`, icon: 'scan', tone: 'amber', width: batches.length ? Math.min(100, Math.max(18, pendingBatches / batches.length * 100)) : 0 },
    { label: '试卷建设', value: paperCount, note: `已批阅 ${gradedTotal} 份`, icon: 'file-text', tone: 'green', width: paperCount ? Math.min(100, Math.max(18, gradedTotal / Math.max(gradedTotal, paperCount) * 100)) : 0 },
  ] : [
    { label: '我的课表', value: '—', note: '课表生成后显示', icon: 'calendar', tone: 'blue', width: 0 },
    { label: '任教班级', value: '—', note: '按当前角色显示', icon: 'users', tone: 'violet', width: 0 },
    { label: '近期考试', value: exams.length, note: `${ongoingExams} 场进行中`, icon: 'file-text', tone: 'amber', width: exams.length ? 60 : 0 },
  ]

  return <div className="wb-page"><Spin spinning={loading}>
    <header className="wb-header"><div><span className="wb-kicker"><i />{copy.label} · {schoolCode || '当前学校'}</span><h1>{copy.title}</h1><p>{copy.subtitle}</p></div><div className="wb-header-meta"><span className="wb-sync"><i />数据已同步</span><span>{dayjs().format('YYYY年M月D日')}</span><b>{dayjs().format('dddd')}</b></div></header>

    {role === 'academic' && <section className="wb-flow" aria-label="教务业务流程"><div className="wb-flow-heading"><b>本学期推进</b><span>从基础配置到结果发布</span></div><div className="wb-flow-track">{['班级与资源', '任教关系', '排课', '排考', '发布'].map((step, index) => <div className={`wb-flow-step ${index === 2 ? 'active' : ''}`} key={step}><i /><span>{step}</span>{index < 4 && <hr />}</div>)}</div></section>}

    <section className="wb-metrics" aria-label="工作台统计">{role === 'academic' ? <><Metric icon="users" label="当前学生" value={studentTotal} suffix="人" hint="学生名册" /><Metric icon="calendar" label="进行中考试" value={ongoingExams} suffix="场" hint="需要关注的考试" /><Metric icon="scan" label="待处理批次" value={pendingBatches} suffix="批" hint="扫描进卷" /><Metric icon="file-text" label="已建试卷" value={paperCount} suffix="份" hint={`已批阅 ${gradedTotal} 份`} /></> : <><Metric icon="calendar" label="今日课程" value="—" suffix="节" hint="课表生成后显示" /><Metric icon="users" label="任教班级" value="—" suffix="个" hint="按当前角色显示" /><Metric icon="file-text" label="近期考试" value={exams.length} suffix="场" hint="考试安排" /><Metric icon="list" label="待处理事项" value={pendingBatches} suffix="项" hint="需要及时处理" /></>}</section>

    <section className="wb-visual-grid" aria-label="工作状态可视化"><div className="wb-visual-panel"><div className="wb-panel-head"><div><span className="wb-section-label">工作状态</span><h2>当前进度</h2></div><span className="wb-live"><i />实时数据</span></div><div className="wb-visual-rows">{visualRows.map((row) => <div className="wb-visual-row" key={row.label}><span className={`wb-visual-icon ${row.tone}`}><Icon name={row.icon} size={17} /></span><span className="wb-visual-name"><b>{row.label}</b><small>{row.note}</small></span><strong>{row.value}</strong><span className="wb-progress"><i style={{ width: `${row.width}%` }} /></span></div>)}</div></div><div className="wb-visual-panel wb-next-panel"><div className="wb-panel-head"><div><span className="wb-section-label">业务指引</span><h2>下一步</h2></div><Icon name="arrow-right" size={16} /></div><div className="wb-next-content"><span className="wb-next-mark"><Icon name={role === 'academic' ? 'calendar' : 'book'} size={22} /></span><div><b>{role === 'academic' ? '先确认任教关系，再生成课表' : '从我的课表开始'}</b><small>{role === 'academic' ? '规则、教师和教室都准备好后，排课结果才可落地。' : '进入对应业务页面查看当前学期安排。'}</small></div></div><Button type="primary" onClick={() => navigate(role === 'academic' ? '/scheduling' : '/scheduling')}>进入{role === 'academic' ? '排课' : '课表'} <Icon name="arrow-right" size={14} /></Button></div></section>

    <section className="wb-section"><div className="wb-section-head"><div><span className="wb-section-label">快捷入口</span><h2>{role === 'academic' ? '教务工作流' : '我的工作'}</h2></div></div><div className="wb-action-grid">{actions[role].map((action) => <ActionCard key={action.title} action={action} onClick={() => navigate(action.path)} />)}</div></section>

    <div className="wb-columns"><section className="wb-panel"><div className="wb-panel-head"><div><span className="wb-section-label">最近动态</span><h2>考试安排</h2></div><Button type="text" onClick={() => navigate('/exams')}>查看全部 <Icon name="arrow-right" size={14} /></Button></div>{!exams.length ? <EmptyState icon="calendar" title="暂无考试安排" desc="创建考试后，安排会显示在这里。" actionText="去创建考试" height={190} onAction={() => navigate('/exams')} /> : <div className="wb-exam-list">{exams.slice(0, 5).map((exam) => <button type="button" className="wb-exam-row" key={exam.id} onClick={() => navigate('/exams')}><span className="wb-exam-date">{exam.created_at ? dayjs(exam.created_at).format('MM/DD') : '—'}</span><span className="wb-exam-name">{exam.name}</span><span className="wb-exam-type">{EXAM_TYPE_DICT[exam.exam_type || '']?.label || '考试'}</span><DictTag dict={EXAM_STATUS_DICT} value={exam.status} /><Icon name="chevron-right" size={14} className="wb-arrow" /></button>)}</div>}</section>

      <section className="wb-panel"><div className="wb-panel-head"><div><span className="wb-section-label">需要处理</span><h2>待办事项</h2></div></div><div className="wb-todo-list">{role === 'academic' && <button type="button" onClick={() => navigate('/scheduling')}><span className="wb-todo-dot blue" /><span><b>检查排课条件</b><small>确认规则与任教关系后生成课表</small></span><Icon name="arrow-right" size={14} /></button>}<button type="button" onClick={() => navigate(role === 'academic' ? '/exam-rooms' : '/exam-calendar')}><span className="wb-todo-dot amber" /><span><b>{role === 'academic' ? '准备考试场室' : '查看近期考试'}</b><small>{role === 'academic' ? '先建考场，再安排考生与监考人员' : '确认考试时间与考场安排'}</small></span><Icon name="arrow-right" size={14} /></button><button type="button" onClick={() => navigate(role === 'teacher' ? '/teacher-profiles' : '/classes')}><span className="wb-todo-dot green" /><span><b>{role === 'teacher' ? '查看任教班级' : '查看班级信息'}</b><small>{role === 'teacher' ? '查看当前学期的授课范围' : '进入班级名单处理学生与班级'}</small></span><Icon name="arrow-right" size={14} /></button></div></section></div>

    {role === 'academic' && <section className="wb-panel wb-scan-panel"><div className="wb-panel-head"><div><span className="wb-section-label">进卷状态</span><h2>扫描批次</h2></div><Button type="text" onClick={() => navigate('/scans')}>进入进卷中心 <Icon name="arrow-right" size={14} /></Button></div>{!batches.length ? <div className="wb-inline-empty"><Icon name="scan" size={19} /><span>暂无扫描批次，试卷定稿后可上传扫描件。</span><Button size="small" onClick={() => navigate('/scans')}>去上传</Button></div> : <div className="wb-batch-list">{batches.slice(0, 4).map((batch) => <div className="wb-batch-row" key={batch.id}><span>{batch.file_name || `扫描批次 #${batch.id}`}</span><span>{batch.page_count ?? 0} 页</span><DictTag dict={SCAN_BATCH_STATUS_DICT} value={batch.status} /><span>{batch.created_at ? dayjs(batch.created_at).format('YYYY-MM-DD') : '—'}</span></div>)}</div>}</section>}
  </Spin></div>
}
