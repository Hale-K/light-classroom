import type { ScheduleEntry } from '@/types'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

interface ScheduleGridProps {
  entries: ScheduleEntry[]
  periods?: number
  days?: number
  dailyPeriods?: number[]
  showEvening?: boolean
  eveningStartPeriod?: number | null
  showClassName?: boolean
  /** 表头附加日期列（排考/走班日历用） */
  dateMode?: boolean
  weekStart?: string
  onLessonContextMenu?: (entry: ScheduleEntry, event: React.MouseEvent<HTMLDivElement>) => void
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
  const headers = WEEKDAY_LABELS.slice(0, days).map((label, index) => {
    const weekday = index + 1
    const item = entries.find((e) => e.weekday === weekday && e.lesson_date)
    let date = item?.lesson_date
    if (!date && dateMode && weekStart) {
      const day = new Date(`${weekStart}T00:00:00`)
      day.setDate(day.getDate() + index)
      date = [
        day.getFullYear(),
        String(day.getMonth() + 1).padStart(2, '0'),
        String(day.getDate()).padStart(2, '0'),
      ].join('-')
    }
    return { label, date: date?.slice(5), fullDate: date }
  })

  const lessons = (weekday: number, period: number) =>
    entries.filter((e) => e.weekday === weekday && e.period === period)
  const eveningLessons = (weekday: number) => entries.filter((e) => (
    e.weekday === weekday && e.period >= (eveningStartPeriod ?? periods + 1)
  ))
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
  const renderEntries = (cellEntries: ScheduleEntry[]) => {
    const ordered = [...cellEntries].sort((left, right) => {
      const parityOrder = { odd: 0, even: 1, all: 2 }
      return (parityOrder[left.week_parity || 'all'] ?? 2) - (parityOrder[right.week_parity || 'all'] ?? 2)
    })
    const tones = ordered.map((lesson) => subjectTone(lesson.subject_name || '未知学科'))
    const tone = tones.length > 1 ? 'multi' : tones[0] || 'default'
    const classNames = [...new Set(ordered.map((lesson) => lesson.class_name).filter(Boolean))]
    return (
      <div className={`st-lessons st-tone-${tone}`}>
        <div className="st-subject-line">
          {ordered.map((lesson, index) => {
            const subjectName = lesson.subject_name || '未知学科'
            return (
              <span className="st-subject-token" key={`${lesson.subject_id}-${lesson.week_parity || 'all'}-${index}`}>
                {index > 0 && <span className="st-subject-divider" aria-hidden="true">·</span>}
                <strong className={`st-subject-name st-subject-${subjectTone(subjectName)}`}>{subjectName}</strong>
              </span>
            )
          })}
        </div>
        {showClassName && classNames.length > 0 && (
          <small className="st-class-line">{classNames.join(' ｜ ')}</small>
        )}
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
      <div key={`head-${h.label}`} className={`st-day-head${h.fullDate === todayValue ? ' current' : ''}`}>
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
    for (let weekday = 1; weekday <= days; weekday += 1) {
      const cellEntries = lessons(weekday, period)
      const entry = cellEntries[0]
      cells.push(
        <div
          key={`lesson-${weekday}-${period}`}
          className={`st-lesson${entry ? ' filled' : ''}${dailyPeriods && period > (dailyPeriods[weekday - 1] ?? periods) ? ' unavailable' : ''}`}
          onContextMenu={entry && onLessonContextMenu ? (event) => onLessonContextMenu(entry, event) : undefined}
        >
          {dailyPeriods && period > (dailyPeriods[weekday - 1] ?? periods) ? (
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
    cells.push(
      <div key="period-evening" className="st-period st-evening-period">
        <strong>晚自习</strong>
        <small>每天 1 节</small>
      </div>,
    )
    for (let weekday = 1; weekday <= days; weekday += 1) {
      const cellEntries = eveningLessons(weekday)
      cells.push(
        <div key={`evening-${weekday}`} className={`st-lesson${cellEntries.length ? ' filled' : ''}`}>
          {cellEntries.length ? (
            renderEntries(cellEntries)
          ) : (
            <span className="st-empty-mark">—</span>
          )}
        </div>,
      )
    }
  }

  return (
    <div className="schedule-table-wrap" role="region" aria-label="课程表" tabIndex={0}>
      <div className="schedule-table" style={{ '--schedule-days': days } as React.CSSProperties}>{cells}</div>
    </div>
  )
}
