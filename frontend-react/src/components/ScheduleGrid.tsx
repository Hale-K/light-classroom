import type { ScheduleEntry } from '@/types'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五']

interface ScheduleGridProps {
  entries: ScheduleEntry[]
  periods?: number
  /** 表头附加日期列（排考/走班日历用） */
  dateMode?: boolean
  weekStart?: string
  onLessonContextMenu?: (entry: ScheduleEntry, event: React.MouseEvent<HTMLDivElement>) => void
}

/** 课表大表：节次 × 星期 网格，适配打印 */
export default function ScheduleGrid({
  entries,
  periods = 7,
  dateMode = false,
  weekStart = '',
  onLessonContextMenu,
}: ScheduleGridProps) {
  const headers = WEEKDAY_LABELS.map((label, index) => {
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
    return { label, date: date?.slice(5) }
  })

  const lesson = (weekday: number, period: number) =>
    entries.find((e) => e.weekday === weekday && e.period === period)

  const cells: React.ReactNode[] = []
  cells.push(
    <div key="corner" className="st-corner">
      <span>节次</span>
      <small>时间</small>
    </div>,
  )
  headers.forEach((h) => {
    cells.push(
      <div key={`head-${h.label}`} className="st-day-head">
        <strong>{h.label}</strong>
        {dateMode && <small>{h.date || '—'}</small>}
      </div>,
    )
  })
  for (let period = 1; period <= periods; period += 1) {
    cells.push(
      <div key={`period-${period}`} className="st-period">
        <strong>{period}</strong>
        <small>第 {period} 节</small>
      </div>,
    )
    for (let weekday = 1; weekday <= 5; weekday += 1) {
      const entry = lesson(weekday, period)
      cells.push(
        <div
          key={`lesson-${weekday}-${period}`}
          className={`st-lesson${entry ? ' filled' : ''}`}
          onContextMenu={entry && onLessonContextMenu ? (event) => onLessonContextMenu(entry, event) : undefined}
        >
          {entry ? (
            <>
              <strong>{entry.subject_name}</strong>
              <span>{entry.teacher_name}</span>
              {entry.room && <small>{entry.room}</small>}
            </>
          ) : (
            <span className="st-empty-mark">—</span>
          )}
        </div>,
      )
    }
  }

  return (
    <div className="schedule-table-wrap" role="region" aria-label="课程表" tabIndex={0}>
      <div className="schedule-table">{cells}</div>
    </div>
  )
}
