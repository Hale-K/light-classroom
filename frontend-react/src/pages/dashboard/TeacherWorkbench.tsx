import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Calendar, Checkbox, Input, Progress, Spin } from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { orgApi, schedulingApi, teacherProfilesApi } from '@/api'
import Icon from '@/components/Icon'
import ScheduleGrid from '@/components/ScheduleGrid'
import { selectDisplayName, useAuthStore } from '@/store/auth'
import type { ClassInfo, ScheduleEntry, SchedulingGridConfig, TeacherScheduleEntry } from '@/types'
import './index.css'

type TeacherView = 'subject' | 'head'

interface ClassPill {
  id: number
  name: string
  subjectHint?: string
}

interface DiamondItem {
  id: string
  label: string
  icon: string
  tone: 'blue' | 'amber' | 'green' | 'violet'
  type: 'route' | 'external'
  target: string
}

interface TodoItem {
  id: string
  text: string
  done: boolean
}

const VIEW_KEY = 'wb_teacher_view'
const CLASS_KEY = 'wb_teacher_class'
const MEMO_KEY = 'wb_teacher_memo'
const TODO_KEY = 'wb_teacher_todos'
const DIAMOND_KEY = 'wb_teacher_diamond'

const SUBJECT_DIAMOND: DiamondItem[] = [
  { id: 'schedule', label: '我的课表', icon: 'calendar', tone: 'blue', type: 'route', target: '/scheduling' },
  { id: 'exams', label: '考试阅卷', icon: 'edit', tone: 'green', type: 'route', target: '/exams' },
  { id: 'invigilate', label: '监考安排', icon: 'file-text', tone: 'amber', type: 'route', target: '/exam-invigilators' },
  { id: 'files', label: '文件中心', icon: 'upload', tone: 'violet', type: 'route', target: '/file-center' },
  { id: 'profiles', label: '任教班级', icon: 'users', tone: 'blue', type: 'route', target: '/teacher-profiles' },
  { id: 'students', label: '学生档案', icon: 'id-badge', tone: 'green', type: 'route', target: '/students' },
  { id: 'settings', label: '系统设置', icon: 'settings', tone: 'amber', type: 'route', target: '/settings' },
  { id: 'manage', label: '管理入口', icon: 'plus', tone: 'violet', type: 'route', target: '/dashboard' },
]

const HEAD_DIAMOND: DiamondItem[] = [
  { id: 'classes', label: '班级名单', icon: 'users', tone: 'blue', type: 'route', target: '/classes' },
  { id: 'seating', label: '班级排座', icon: 'grid', tone: 'violet', type: 'route', target: '/seating' },
  { id: 'exam-cal', label: '考试安排', icon: 'calendar', tone: 'amber', type: 'route', target: '/exam-calendar' },
  { id: 'schedule', label: '班级课表', icon: 'book', tone: 'green', type: 'route', target: '/scheduling' },
  { id: 'students', label: '学生档案', icon: 'id-badge', tone: 'blue', type: 'route', target: '/students' },
  { id: 'files', label: '文件中心', icon: 'upload', tone: 'violet', type: 'route', target: '/file-center' },
  { id: 'meetings', label: '会议管理', icon: 'message', tone: 'amber', type: 'route', target: '/meetings' },
  { id: 'manage', label: '管理入口', icon: 'plus', tone: 'green', type: 'route', target: '/dashboard' },
]

function greetingByHour(hour = dayjs().hour()) {
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

function currentTerm() {
  const now = dayjs()
  const academicYear = now.month() >= 7
    ? `${now.year()}-${now.year() + 1}`
    : `${now.year() - 1}-${now.year()}`
  const term = now.month() >= 1 && now.month() < 7 ? '2' : '1'
  return { academicYear, term }
}

function weekIndex(termStartMonday: string | null | undefined) {
  if (!termStartMonday) return null
  const start = dayjs(termStartMonday).startOf('day')
  if (!start.isValid()) return null
  const days = dayjs().startOf('day').diff(start, 'day')
  if (days < 0) return 1
  return Math.floor(days / 7) + 1
}

function termProgress(termStartMonday: string | null | undefined) {
  if (!termStartMonday) return { percent: 0, label: '尚未配置学期首周' }
  const start = dayjs(termStartMonday).startOf('day')
  if (!start.isValid()) return { percent: 0, label: '学期日期无效' }
  const end = start.add(20, 'week').subtract(1, 'day')
  const total = Math.max(1, end.diff(start, 'day'))
  const elapsed = Math.min(total, Math.max(0, dayjs().startOf('day').diff(start, 'day')))
  const percent = Math.round((elapsed / total) * 100)
  return { percent, label: `${start.format('M/D')} — ${end.format('M/D')}` }
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
  const roles = user?.roles || []
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
  const [allClasses, setAllClasses] = useState<ClassInfo[]>([])
  const [teachingPills, setTeachingPills] = useState<ClassPill[]>([])
  const [headPills, setHeadPills] = useState<ClassPill[]>([])
  const [gridConfig, setGridConfig] = useState<SchedulingGridConfig | null>(null)
  const [entries, setEntries] = useState<ScheduleEntry[]>([])
  const [search, setSearch] = useState('')
  const [memo, setMemo] = useState(() => localStorage.getItem(`${MEMO_KEY}_${teacherId || 0}`) || '')
  const [todos, setTodos] = useState<TodoItem[]>(() =>
    readJson(`${TODO_KEY}_${teacherId || 0}`, [
      { id: '1', text: '检查本周课表', done: false },
      { id: '2', text: '整理待办事项', done: false },
    ]),
  )
  const [todoDraft, setTodoDraft] = useState('')
  const [calendarMonth, setCalendarMonth] = useState(() => dayjs())

  const showViewSwitch = canHead && roles.includes('subject_teacher')
  const classPills = view === 'head' ? headPills : teachingPills
  const activeClassId = classPills.some((c) => c.id === classId) ? classId : (classPills[0]?.id ?? null)
  const weekNo = weekIndex(gridConfig?.term_start_monday)
  const progress = termProgress(gridConfig?.term_start_monday)
  const greeting = greetingByHour()

  const diamondItems = useMemo(() => {
    const defaults = view === 'head' ? HEAD_DIAMOND : SUBJECT_DIAMOND
    const saved = readJson<DiamondItem[] | null>(`${DIAMOND_KEY}_${view}`, null)
    return saved && saved.length ? saved : defaults
  }, [view])

  useEffect(() => {
    localStorage.setItem(VIEW_KEY, view)
  }, [view])

  useEffect(() => {
    if (activeClassId != null) localStorage.setItem(CLASS_KEY, String(activeClassId))
  }, [activeClassId])

  useEffect(() => {
    localStorage.setItem(`${MEMO_KEY}_${teacherId || 0}`, memo)
  }, [memo, teacherId])

  useEffect(() => {
    localStorage.setItem(`${TODO_KEY}_${teacherId || 0}`, JSON.stringify(todos))
  }, [todos, teacherId])

  useEffect(() => {
    if (!teacherId) return
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const [resources, classes, grid] = await Promise.all([
          schedulingApi.resources(),
          orgApi.classes(),
          schedulingApi.gridConfig({ academic_year: academicYear, term }),
        ])
        if (cancelled) return
        setAllClasses(classes)
        setGridConfig(grid)
        const myAssignments = resources.assignments.filter(
          (a) => a.teacher_id === teacherId && a.academic_year === academicYear && a.term === term,
        )
        const teach = uniqueClassPills(
          myAssignments.map((a) => {
            const cls = resources.classes.find((c) => c.id === a.class_id) || classes.find((c) => c.id === a.class_id)
            const subject = resources.subjects.find((s) => s.id === a.subject_id)
            return {
              id: a.class_id,
              name: cls?.name || `班级 ${a.class_id}`,
              subjectHint: subject?.name,
            }
          }),
        )
        const head = classes
          .filter((c) => c.head_teacher_id === teacherId)
          .map((c) => ({ id: c.id, name: c.name }))
        setTeachingPills(teach)
        setHeadPills(head)
        if (canHead && head.length && !roles.includes('subject_teacher')) {
          setView('head')
        }
      } catch {
        if (!cancelled) message.error('加载教师工作台失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [academicYear, canHead, message, roles, teacherId, term])

  const loadSchedule = useCallback(async () => {
    if (!teacherId) return
    setScheduleLoading(true)
    try {
      if (view === 'subject') {
        const result = await teacherProfilesApi.weeklySchedule(teacherId, {
          academic_year: academicYear,
          term,
        })
        setEntries(mapTeacherEntries(result.items || []))
      } else if (activeClassId != null) {
        const weekly = await schedulingApi.weekly({
          class_id: activeClassId,
          academic_year: academicYear,
          term,
        })
        setEntries(weekly)
      } else {
        setEntries([])
      }
    } catch {
      setEntries([])
      message.error('加载课表失败')
    } finally {
      setScheduleLoading(false)
    }
  }, [academicYear, activeClassId, message, teacherId, term, view])

  useEffect(() => {
    void loadSchedule()
  }, [loadSchedule])

  const todayLessons = useMemo(() => {
    const weekday = ((dayjs().day() + 6) % 7) + 1
    return entries.filter((e) => e.weekday === weekday && (view === 'subject' || e.teacher_id === teacherId))
  }, [entries, teacherId, view])

  const lessonDates = useMemo(() => {
    const start = gridConfig?.term_start_monday ? dayjs(gridConfig.term_start_monday) : dayjs().startOf('week')
    const set = new Set<string>()
    for (let w = 0; w < 22; w += 1) {
      for (const entry of entries) {
        if (view === 'head' && entry.teacher_id !== teacherId) continue
        const d = start.add(w, 'week').add(entry.weekday - 1, 'day')
        set.add(d.format('YYYY-MM-DD'))
      }
    }
    return set
  }, [entries, gridConfig?.term_start_monday, teacherId, view])

  const onDiamondClick = (item: DiamondItem) => {
    if (item.type === 'external') {
      window.open(item.target, '_blank', 'noopener,noreferrer')
      return
    }
    navigate(item.target)
  }

  const filteredDiamond = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return diamondItems
    return diamondItems.filter((item) => item.label.toLowerCase().includes(q) || item.target.toLowerCase().includes(q))
  }, [diamondItems, search])

  const matchedClasses = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return []
    return allClasses.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 6)
  }, [allClasses, search])

  const addTodo = () => {
    const text = todoDraft.trim()
    if (!text) return
    setTodos((prev) => [...prev, { id: `${Date.now()}`, text, done: false }])
    setTodoDraft('')
  }

  const dateCellRender = (value: Dayjs) => {
    const key = value.format('YYYY-MM-DD')
    if (!lessonDates.has(key)) return null
    return <span className="tw-cal-dot" title="有课" />
  }

  return (
    <div className="tw-page">
      <Spin spinning={loading}>
        <header className="tw-header">
          <div className="tw-header-main">
            <div className="tw-date-line">
              <strong>{dayjs().format('M月D日')}</strong>
              <span>{dayjs().format('dddd')}</span>
              {weekNo != null && <em>第 {weekNo} 周</em>}
            </div>
            <h1>
              {displayName || '老师'}，{greeting}
            </h1>
            <p>
              {view === 'head' ? '班主任视角 · 班级事务与全班课表' : '任教视角 · 我的授课安排'}
              {activeClassId != null && classPills.find((c) => c.id === activeClassId)
                ? ` · ${classPills.find((c) => c.id === activeClassId)?.name}`
                : ''}
            </p>
          </div>
          <div className="tw-header-side">
            <span className="tw-today-count">今日 {todayLessons.length} 节</span>
            <span>{academicYear} 学年 · 第 {term} 学期</span>
          </div>
        </header>

        {showViewSwitch && (
          <div className="tw-view-tabs" role="tablist" aria-label="工作台视角">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'subject'}
              className={view === 'subject' ? 'active' : ''}
              onClick={() => setView('subject')}
            >
              任教视角
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'head'}
              className={view === 'head' ? 'active' : ''}
              onClick={() => setView('head')}
            >
              班主任视角
            </button>
          </div>
        )}

        {classPills.length > 0 && (
          <div className="tw-class-rail" aria-label="班级选择">
            {classPills.map((cls) => (
              <button
                key={cls.id}
                type="button"
                className={`tw-class-pill${activeClassId === cls.id ? ' active' : ''}`}
                onClick={() => setClassId(cls.id)}
              >
                <b>{cls.name}</b>
                {cls.subjectHint && <small>{cls.subjectHint}</small>}
              </button>
            ))}
          </div>
        )}

        <div className="tw-search">
          <Icon name="search" size={16} />
          <Input
            variant="borderless"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索班级、功能入口…"
            onPressEnter={() => {
              if (matchedClasses[0]) {
                setClassId(matchedClasses[0].id)
                setSearch('')
                return
              }
              if (filteredDiamond[0]) onDiamondClick(filteredDiamond[0])
            }}
          />
        </div>
        {(search.trim() && (matchedClasses.length > 0 || filteredDiamond.length > 0)) && (
          <div className="tw-search-hits">
            {matchedClasses.map((cls) => (
              <button key={cls.id} type="button" onClick={() => { setClassId(cls.id); setSearch('') }}>
                班级 · {cls.name}
              </button>
            ))}
            {filteredDiamond.map((item) => (
              <button key={item.id} type="button" onClick={() => onDiamondClick(item)}>
                功能 · {item.label}
              </button>
            ))}
          </div>
        )}

        <div className="tw-split">
          <section className="tw-panel tw-memo">
            <div className="tw-panel-head">
              <span>编辑工作区</span>
            </div>
            <Input.TextArea
              value={memo}
              onChange={(e) => setMemo(e.target.value)}
              placeholder="随手记下备课要点、班会提纲…"
              autoSize={{ minRows: 4, maxRows: 8 }}
            />
          </section>
          <section className="tw-panel tw-todo">
            <div className="tw-panel-head">
              <span>待办清单</span>
              <small>{todos.filter((t) => !t.done).length} 项未完成</small>
            </div>
            <div className="tw-todo-list">
              {todos.map((todo) => (
                <label key={todo.id} className={todo.done ? 'done' : ''}>
                  <Checkbox
                    checked={todo.done}
                    onChange={(e) => setTodos((prev) => prev.map((t) => (t.id === todo.id ? { ...t, done: e.target.checked } : t)))}
                  />
                  <span>{todo.text}</span>
                  <button
                    type="button"
                    aria-label="删除"
                    onClick={() => setTodos((prev) => prev.filter((t) => t.id !== todo.id))}
                  >
                    ×
                  </button>
                </label>
              ))}
            </div>
            <div className="tw-todo-add">
              <Input
                value={todoDraft}
                onChange={(e) => setTodoDraft(e.target.value)}
                placeholder="添加待办"
                onPressEnter={addTodo}
              />
              <button type="button" onClick={addTodo}>添加</button>
            </div>
          </section>
        </div>

        <section className="tw-panel tw-schedule">
          <div className="tw-panel-head">
            <div>
              <span>课表</span>
              <h2>
                {view === 'subject'
                  ? '我的周课表'
                  : `${classPills.find((c) => c.id === activeClassId)?.name || '班级'}课表`}
              </h2>
            </div>
            <small>{view === 'head' ? '紫色高亮为我的课' : '展示本周授课安排'}</small>
          </div>
          <Spin spinning={scheduleLoading}>
            {entries.length === 0 ? (
              <div className="tw-empty">暂无课表，请先完成排课生成。</div>
            ) : (
              <ScheduleGrid
                entries={entries}
                periods={gridConfig?.periods_per_day || 7}
                days={gridConfig?.days || 5}
                dailyPeriods={gridConfig?.daily_periods}
                showEvening={Boolean(gridConfig?.enable_evening)}
                eveningStartPeriod={gridConfig?.evening_start_period}
                showClassName={view === 'subject'}
                highlightTeacherId={teacherId}
              />
            )}
          </Spin>
        </section>

        <div className="tw-split tw-split-bottom">
          <section className="tw-panel tw-progress">
            <div className="tw-panel-head">
              <span>学期进度</span>
              <strong>{progress.percent}%</strong>
            </div>
            <Progress percent={progress.percent} showInfo={false} strokeColor="#7c3aed" />
            <p>{progress.label}</p>
          </section>
          <section className="tw-panel tw-calendar">
            <div className="tw-panel-head">
              <span>日历</span>
            </div>
            <Calendar
              fullscreen={false}
              value={calendarMonth}
              onChange={setCalendarMonth}
              cellRender={(current, info) => (info.type === 'date' ? dateCellRender(current) : null)}
            />
          </section>
        </div>

        <section className="tw-panel tw-diamond" aria-label="金刚区">
          <div className="tw-panel-head">
            <span>快捷入口</span>
            <small>2×4 · 菜单或外链</small>
          </div>
          <div className="tw-diamond-grid">
            {(search.trim() ? filteredDiamond : diamondItems).slice(0, 8).map((item) => (
              <button
                key={item.id}
                type="button"
                className="tw-diamond-item"
                onClick={() => onDiamondClick(item)}
              >
                <span className={`tw-diamond-icon ${item.tone}`}>
                  <Icon name={item.icon} size={18} />
                </span>
                <b>{item.label}</b>
              </button>
            ))}
          </div>
        </section>
      </Spin>
    </div>
  )
}
