import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, App, Checkbox, Input, Spin } from 'antd'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { orgApi, schedulingApi, teacherProfilesApi } from '@/api'
import Icon from '@/components/Icon'
import { selectDisplayName, useAuthStore } from '@/store/auth'
import type { ScheduleEntry, TeacherScheduleEntry } from '@/types'
import './teacher-workbench.css'

type TeacherView = 'subject' | 'head'

interface ClassPill {
  id: number
  name: string
  subjectHint?: string
}

interface TodoItem {
  id: string
  text: string
  done: boolean
}

const VIEW_KEY = 'wb_teacher_view'
const CLASS_KEY = 'wb_teacher_class'
const TODO_KEY = 'wb_teacher_todos'
function currentTerm() {
  const now = dayjs()
  const academicYear = now.month() >= 7
    ? `${now.year()}-${now.year() + 1}`
    : `${now.year() - 1}-${now.year()}`
  const term = now.month() >= 1 && now.month() < 7 ? '2' : '1'
  return { academicYear, term }
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function mapTeacherEntries(items: TeacherScheduleEntry[]): ScheduleEntry[] {
  return (items || []).map((item) => ({
    id: item.id,
    class_id: item.class_id,
    weekday: item.weekday,
    period: item.period,
    subject_id: item.subject_id,
    teacher_id: item.teacher_id,
    room: item.room,
    academic_year: item.academic_year,
    term: item.term,
    teacher_name: item.teacher_name,
    subject_name: item.subject_name,
    class_name: item.class_name,
  }))
}

function uniqueClassPills(items: ClassPill[]) {
  const map = new Map<number, ClassPill>()
  for (const item of items) {
    const prev = map.get(item.id)
    if (!prev) {
      map.set(item.id, item)
      continue
    }
    if (item.subjectHint && prev.subjectHint && !prev.subjectHint.includes(item.subjectHint)) {
      map.set(item.id, { ...prev, subjectHint: `${prev.subjectHint}/${item.subjectHint}` })
    }
  }
  return [...map.values()]
}

export default function TeacherWorkbench() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const user = useAuthStore((s) => s.user)
  const displayName = useAuthStore(selectDisplayName)
  const teacherId = user?.id
  const roles = useMemo(() => user?.roles || [], [user?.roles])
  const canHead = roles.includes('head_teacher')

  const { academicYear, term } = useMemo(() => currentTerm(), [])
  const [view, setView] = useState<TeacherView>(() => {
    const saved = localStorage.getItem(VIEW_KEY) as TeacherView | null
    if (saved === 'head' && canHead) return 'head'
    if (saved === 'subject') return 'subject'
    return canHead && !roles.includes('subject_teacher') ? 'head' : 'subject'
  })
  const [classId, setClassId] = useState<number | null>(() => {
    const raw = localStorage.getItem(CLASS_KEY)
    const n = raw ? Number(raw) : NaN
    return Number.isFinite(n) ? n : null
  })
  const [loading, setLoading] = useState(true)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [scheduleError, setScheduleError] = useState(false)
  const [resourcesError, setResourcesError] = useState(false)
  const [teachingPills, setTeachingPills] = useState<ClassPill[]>([])
  const [headPills, setHeadPills] = useState<ClassPill[]>([])
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [todos, setTodos] = useState<TodoItem[]>(() =>
    readJson(`${TODO_KEY}_${teacherId || 0}`, [
      { id: '1', text: '检查本周课表', done: false },
      { id: '2', text: '整理待办事项', done: false },
    ]),
  )
  const [todoDraft, setTodoDraft] = useState('')

  const showViewSwitch = canHead && roles.includes('subject_teacher')
  const classPills = view === 'head' ? headPills : teachingPills
  const activeClassId = classPills.some((c) => c.id === classId) ? classId : (classPills[0]?.id ?? null)
  useEffect(() => { localStorage.setItem(VIEW_KEY, view) }, [view])
  useEffect(() => { if (activeClassId != null) localStorage.setItem(CLASS_KEY, String(activeClassId)) }, [activeClassId])
  useEffect(() => { localStorage.setItem(`${TODO_KEY}_${teacherId || 0}`, JSON.stringify(todos)) }, [todos, teacherId])

  useEffect(() => {
    if (!teacherId) return
    let cancelled = false
    void (async () => {
      setLoading(true)
      setResourcesError(false)
      try {
        const [resources, classes] = await Promise.all([
          schedulingApi.resources(),
          orgApi.classes(),
        ])
        if (cancelled) return
        const myAssignments = resources.assignments.filter(
          (a) => a.teacher_id === teacherId && a.academic_year === academicYear && a.term === term,
        )
        const teach = uniqueClassPills(
          myAssignments.map((a) => {
            const cls = resources.classes.find((c) => c.id === a.class_id) || classes.find((c) => c.id === a.class_id)
            const subject = resources.subjects.find((s) => s.id === a.subject_id)
            return { id: a.class_id, name: cls?.name || `班级 ${a.class_id}`, subjectHint: subject?.name }
          }),
        )
        const head = classes.filter((c) => c.head_teacher_id === teacherId).map((c) => ({ id: c.id, name: c.name }))
        setTeachingPills(teach)
        setHeadPills(head)
        if (canHead && head.length && !roles.includes('subject_teacher')) setView('head')
      } catch {
        if (!cancelled) { setResourcesError(true); message.error('加载教师工作台失败') }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [academicYear, canHead, message, roles, teacherId, term])

  const loadSchedule = useCallback(async () => {
    if (!teacherId) return
    setScheduleLoading(true)
    setScheduleError(false)
    try {
      if (view === 'subject') {
        const result = await teacherProfilesApi.weeklySchedule(teacherId, { academic_year: academicYear, term })
        setEntries(mapTeacherEntries(result.items || []))
      } else if (activeClassId != null) {
        const weekly = await schedulingApi.weekly({ class_id: activeClassId, academic_year: academicYear, term })
        setEntries(weekly)
      } else {
        setEntries([])
      }
    } catch {
      setEntries([])
      setScheduleError(true)
      message.error('加载课表失败')
    } finally {
      setScheduleLoading(false)
    }
  }, [academicYear, activeClassId, message, teacherId, term, view])

  useEffect(() => { void loadSchedule() }, [loadSchedule])

  const todayLessons = useMemo(() => {
    const weekday = ((dayjs().day() + 6) % 7) + 1
    return entries.filter((e) => e.weekday === weekday && (view === 'subject' || e.teacher_id === teacherId))
  }, [entries, teacherId, view])

  const sortedToday = [...todayLessons].sort((a, b) => a.period - b.period)
  const pending = todos.filter((item) => !item.done).length
  const addTodo = () => {
    const text = todoDraft.trim()
    if (!text) return
    setTodos((prev) => [...prev, { id: crypto.randomUUID(), text, done: false }])
    setTodoDraft('')
  }

  return (
    <div className="teacher-desk">
      <Spin spinning={loading}>
        <section className="td-overview">
          <div className="td-greeting">
            <h1>{displayName || '老师'}，今天有 <b>{loading || scheduleLoading || scheduleError ? '—' : todayLessons.length}</b> 节课，<b>{pending}</b> 项待办待完成</h1>
            {showViewSwitch && <select aria-label="工作台身份" value={view} onChange={(event) => setView(event.target.value as TeacherView)}><option value="subject">任课教师</option><option value="head">班主任</option></select>}
          </div>
          <div className="td-stats">
            {[
              { label: '今日概览', icon: 'calendar', value: loading || scheduleLoading || scheduleError ? '—' : todayLessons.length, unit: '节', hint: '今日课程' },
              { label: '待批改', icon: 'edit', value: '—', unit: '份', hint: '暂无批改统计' },
              { label: '待辅导', icon: 'book', value: '—', unit: '人', hint: '暂无辅导统计' },
              { label: '通知', icon: 'message', value: '—', unit: '条', hint: '暂无通知数据' },
            ].map((stat) => <article className="td-stat" key={stat.label}>
              <div className="td-stat-heading"><h2>{stat.label}</h2><span><Icon name={stat.icon} size={17} /></span></div>
              <div className="td-stat-number"><i><Icon name={stat.icon} size={32} /></i><strong>{stat.value}</strong><span>{stat.unit}</span></div>
              <small>{stat.hint}</small>
            </article>)}
          </div>
        </section>
        <div className="td-grid">
          {resourcesError && <Alert className="td-wide" type="error" showIcon message="班级信息加载失败，请刷新页面重试" />}
          <section className="td-card td-schedule">
            <div className="td-section-heading"><h2>今日课表</h2><button onClick={() => navigate('/teacher-courses')}>完整课表 <Icon name="arrow-right" size={14} /></button></div>
            <Spin spinning={scheduleLoading}>
              {scheduleError ? <Alert type="error" showIcon message="课表加载失败" action={<button onClick={() => void loadSchedule()}>重新加载</button>} /> : sortedToday.length ? <div className="td-lessons">{sortedToday.map((lesson) => <div className="td-lesson" key={lesson.id}>
                <strong>第 {lesson.period} 节</strong><span>{lesson.subject_name || '课程'}</span><span>{lesson.class_name || classPills.find((item) => item.id === lesson.class_id)?.name || '班级未命名'}</span><span className="td-room">{lesson.room || '常规课堂'}</span><button onClick={() => navigate('/file-center')}>备课资料</button>
              </div>)}</div> : <div className="td-empty"><Icon name="calendar" size={30} /><p>今天暂无课程安排</p><span>可前往完整课表查看本周教学安排</span></div>}
            </Spin>
          </section>
          <section className="td-card td-todos">
            <div className="td-section-heading"><h2>教学待办</h2><span>{pending} 项未完成</span></div>
            <div className="td-todo-list">{todos.length ? todos.map((todo) => <div className={`td-todo${todo.done ? ' is-done' : ''}`} key={todo.id}><Checkbox checked={todo.done} onChange={(event) => setTodos((prev) => prev.map((item) => item.id === todo.id ? { ...item, done: event.target.checked } : item))}>{todo.text}</Checkbox><button aria-label={`删除待办：${todo.text}`} onClick={() => setTodos((prev) => prev.filter((item) => item.id !== todo.id))}><Icon name="x" size={14} /></button></div>) : <p className="td-muted">待办已清空，添加下一项教学安排吧。</p>}</div>
            <form className="td-add-todo" onSubmit={(event) => { event.preventDefault(); addTodo() }}><Input aria-label="新待办事项" placeholder="添加教学待办…" value={todoDraft} onChange={(event) => setTodoDraft(event.target.value)} maxLength={120} /><button type="submit" disabled={!todoDraft.trim()} aria-label="添加待办"><Icon name="plus" size={18} /></button></form>
          </section>
          <section className="td-card">
            <div className="td-section-heading"><h2>班级关注</h2>{classPills.length > 0 && <select aria-label="关注班级" value={activeClassId ?? ''} onChange={(event) => setClassId(Number(event.target.value))}>{classPills.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}</div>
            <div className="td-attention">{[{ label: '作业异常', icon: 'clipboard' }, { label: '近期考试', icon: 'file-text' }, { label: '成绩波动', icon: 'chart' }].map((item) => <div key={item.label}><i><Icon name={item.icon} size={25} /></i><span><b>{item.label}</b><small>暂无统计数据</small></span></div>)}</div>
          </section>
          <section className="td-card">
            <div className="td-section-heading"><h2>教研活动</h2><button onClick={() => navigate('/meetings')}>会议管理 <Icon name="arrow-right" size={14} /></button></div>
            <div className="td-research"><i><Icon name="users" size={25} /></i><div><b>暂无教研活动数据</b><p>前往会议管理查看教学会议安排</p></div></div>
          </section>
        </div>
      </Spin>
    </div>
  )
}
