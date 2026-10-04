import type { ScheduleEntry } from '@/types'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

type DayParity = 'all' | 'odd' | 'even'

interface DayColumn {
  key: string
  label: string
  weekday: number
  parity: DayParity
}

interface ScheduleGridProps {
  entries: ScheduleEntry[]
  periods?: number
  days?: number
  dailyPeriods?: number[]
  showEvening?: boolean
  eveningStartPeriod?: number | null
  showClassName?: boolean
  /** 高亮该教师的课（班主任看班级课表时标出「我的课」） */
  highlightTeacherId?: number | null
  /** 表头附加日期列（排考/走班日历用） */
  dateMode?: boolean
  weekStart?: string
  onLessonContextMenu?: (entry: ScheduleEntry, event: React.MouseEvent<HTMLDivElement>) => void
}

/** days≥6 时：周一～周五 + 单六 + 双六（+ 周日若有）；否则保持原周一～N */
function buildDayColumns(days: number): DayColumn[] {
  if (days < 6) {
    return Array.from({ length: days }, (_, index) => ({
      key: `d${index + 1}`,
      label: WEEKDAY_LABELS[index],
      weekday: index + 1,
      parity: 'all' as const,
    }))
  }
  const cols: DayColumn[] = [1, 2, 3, 4, 5].map((weekday) => ({
    key: `d${weekday}`,
    label: WEEKDAY_LABELS[weekday - 1],
    weekday,
    parity: 'all' as const,
  }))
  cols.push({ key: 'sat-odd', label: '单六', weekday: 6, parity: 'odd' })
  cols.push({ key: 'sat-even', label: '双六', weekday: 6, parity: 'even' })
  if (days >= 7) {
    cols.push({ key: 'd7', label: '周日', weekday: 7, parity: 'all' })
  }
  return cols
}

function matchesParity(entryParity: ScheduleEntry['week_parity'] | undefined, columnParity: DayParity) {
  const parity = entryParity || 'all'
  if (columnParity === 'all') return true
  return parity === 'all' || parity === columnParity
}

function parityConflicts(left: ScheduleEntry['week_parity'], right: ScheduleEntry['week_parity']) {
  const first = left || 'all'
  const second = right || 'all'
  return first === 'all' || second === 'all' || first === second
}

/** 课表大表：节次 × 星期 网格，适配打印 */
export default function ScheduleGrid({
  entries,
  periods = 7,
  days = 5,
  dailyPeriods,
  showEvening = false,
  eveningStartPeriod,
  showClassName = false,
  highlightTeacherId = null,
  dateMode = false,
  weekStart = '',
  onLessonContextMenu,
}: ScheduleGridProps) {
  const today = new Date()
  const todayValue = [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0'),
  ].join('-')
  const todayWeekday = ((today.getDay() + 6) % 7) + 1
  const dayColumns = buildDayColumns(days)

  const headers = dayColumns.map((column) => {
    const item = entries.find((e) => e.weekday === column.weekday && e.lesson_date)
    let date = item?.lesson_date
    if (!date && dateMode && weekStart) {
      const day = new Date(`${weekStart}T00:00:00`)
      day.setDate(day.getDate() + (column.weekday - 1))
      date = [
        day.getFullYear(),
        String(day.getMonth() + 1).padStart(2, '0'),
        String(day.getDate()).padStart(2, '0'),
      ].join('-')
    }
    return { ...column, date: date?.slice(5), fullDate: date }
  })

  const lessons = (weekday: number, period: number, columnParity: DayParity) =>
    entries.filter(
      (e) =>
        e.weekday === weekday
        && e.period === period
        && matchesParity(e.week_parity, columnParity),
    )

  const eveningLessons = (weekday: number, columnParity: DayParity, rowParity: 'odd' | 'even') => {
    if (weekday === 6 && columnParity !== 'all' && columnParity !== rowParity) {
      return []
    }
    return entries.filter((e) => (
      e.weekday === weekday
      && e.period >= (eveningStartPeriod ?? periods + 1)
      && matchesParity(e.week_parity, rowParity)
    ))
  }

  const subjectTone = (subjectName: string) => {
    if (['语文', '英语'].includes(subjectName)) return 'language'
    if (subjectName === '数学') return 'math'
    if (['物理', '化学', '生物'].includes(subjectName)) return 'science'
    if (['历史', '政治', '地理'].includes(subjectName)) return 'humanities'
    if (subjectName === '体育') return 'pe'
    if (['音乐', '美术', '心理', '校本', '班会', '生涯'].includes(subjectName)) return 'activity'
    if (['自主学习', '不排课'].includes(subjectName)) return 'self-study'
    return 'default'
  }

  const isMine = (entry: ScheduleEntry) =>
    highlightTeacherId != null && entry.teacher_id === highlightTeacherId

  const cellHighlightClass = (cellEntries: ScheduleEntry[]) => {
    if (highlightTeacherId == null || cellEntries.length === 0) return ''
    if (cellEntries.some(isMine)) return ' mine'
    return ' other'
  }

  const renderEntries = (cellEntries: ScheduleEntry[]) => {
    const ordered = [...cellEntries].sort((left, right) => {
      const parityOrder = { odd: 0, even: 1, all: 2 }
      return (parityOrder[left.week_parity || 'all'] ?? 2) - (parityOrder[right.week_parity || 'all'] ?? 2)
    })
    const tones = ordered.map((lesson) => subjectTone(lesson.subject_name || '未知学科'))
    const tone = tones.length > 1 ? 'multi' : tones[0] || 'default'
    const mine = ordered.some(isMine)
    const hasConflict = ordered.some((lesson, index) =>
      ordered.slice(index + 1).some((other) => parityConflicts(lesson.week_parity, other.week_parity)),
    )
    const parityLabel = (parity: ScheduleEntry['week_parity']) => {
      if (parity === 'odd') return '单周'
      if (parity === 'even') return '双周'
      return '整周'
    }
    return (
      <div
        className={`st-lessons st-tone-${tone}${mine ? ' is-mine' : ''}${hasConflict ? ' has-conflict' : ''}`}
        aria-label={hasConflict ? `课位冲突，共 ${ordered.length} 条课程` : undefined}
      >
        {mine && <span className="st-mine-badge" aria-label="我的课">我</span>}
        {hasConflict && <span className="st-conflict-badge">课位冲突</span>}
        <div className="st-entry-list">
          {ordered.map((lesson, index) => {
            const subjectName = lesson.subject_name || '未知学科'
            const showParity = showClassName || hasConflict || lesson.week_parity !== 'all'
            return (
              <div
                className="st-entry"
                key={`${lesson.id}-${lesson.subject_id}-${lesson.week_parity || 'all'}-${index}`}
              >
                <div className="st-subject-line">
                  <strong className={`st-subject-name st-subject-${subjectTone(subjectName)}`}>{subjectName}</strong>
                  {showParity && (
                    <span className={`st-parity-tag st-parity-${lesson.week_parity || 'all'}`}>
                      {parityLabel(lesson.week_parity)}
                    </span>
                  )}
                </div>
                {showClassName && lesson.class_name && <small className="st-class-line">{lesson.class_name}</small>}
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const cells: React.ReactNode[] = []
  cells.push(
    <div key="corner" className="st-corner">
      <span>节次</span>
      <small>时间</small>
    </div>,
  )
  headers.forEach((h) => {
    cells.push(
      <div key={`head-${h.key}`} className={`st-day-head${h.fullDate === todayValue ? ' current' : ''}`}>
        <strong>{h.label}</strong>
        {dateMode && <small>{h.date || '—'}</small>}
      </div>,
    )
  })

  for (let period = 1; period <= periods; period += 1) {
    cells.push(
      <div key={`period-${period}`} className="st-period">
        <strong>第 {period} 节</strong>
      </div>,
    )
    for (const column of dayColumns) {
      const cellEntries = lessons(column.weekday, period, column.parity)
      const entry = cellEntries[0]
      const dayCap = dailyPeriods?.[column.weekday - 1] ?? periods
      const isTodayCol = column.weekday === todayWeekday && column.parity === 'all'
      cells.push(
        <div
          key={`lesson-${column.key}-${period}`}
          className={`st-lesson${entry ? ' filled' : ''}${dailyPeriods && period > dayCap ? ' unavailable' : ''}${cellHighlightClass(cellEntries)}${isTodayCol ? ' today' : ''}`}
          onContextMenu={entry && onLessonContextMenu ? (event) => onLessonContextMenu(entry, event) : undefined}
        >
          {dailyPeriods && period > dayCap ? (
            <span className="st-unavailable-mark">不排课</span>
          ) : entry ? (
            renderEntries(cellEntries)
          ) : (
            <span className="st-empty-mark">—</span>
          )}
        </div>,
      )
    }
  }

  if (showEvening) {
    for (const row of [
      { key: 'odd', label: '晚自习', sub: '单周', parity: 'odd' as const },
      { key: 'even', label: '晚自习', sub: '双周', parity: 'even' as const },
    ]) {
      cells.push(
        <div key={`period-evening-${row.key}`} className="st-period st-evening-period">
          <strong>{row.label}</strong>
          <small>{row.sub}</small>
        </div>,
      )
      for (const column of dayColumns) {
        const cellEntries = eveningLessons(column.weekday, column.parity, row.parity)
        const entry = cellEntries[0]
        const isTodayCol = column.weekday === todayWeekday && column.parity === 'all'
        cells.push(
          <div
            key={`evening-${row.key}-${column.key}`}
            className={`st-lesson${cellEntries.length ? ' filled' : ''}${cellHighlightClass(cellEntries)}${isTodayCol ? ' today' : ''}`}
            onContextMenu={entry && onLessonContextMenu ? (event) => onLessonContextMenu(entry, event) : undefined}
          >
            {cellEntries.length ? (
              renderEntries(cellEntries)
            ) : (
              <span className="st-empty-mark">—</span>
            )}
          </div>,
        )
      }
    }
  }

  return (
    <div className="schedule-table-wrap" role="region" aria-label="课程表" tabIndex={0}>
      <div
        className="schedule-table"
        style={{ '--schedule-days': dayColumns.length } as React.CSSProperties}
      >
        {cells}
      </div>
    </div>
  )
}
