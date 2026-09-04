import type { ScheduleEntry } from '@/types'

const DAY_KEYS = [
  { weekday: 1, parity: 'all' as const },
  { weekday: 2, parity: 'all' as const },
  { weekday: 3, parity: 'all' as const },
  { weekday: 4, parity: 'all' as const },
  { weekday: 5, parity: 'all' as const },
  { weekday: 6, parity: 'odd' as const },
  { weekday: 6, parity: 'even' as const },
]

function matchesParity(
  entryParity: ScheduleEntry['week_parity'] | undefined,
  columnParity: 'all' | 'odd' | 'even',
) {
  const parity = entryParity || 'all'
  if (columnParity === 'all') return true
  return parity === 'all' || parity === columnParity
}

function buildClassCsvBlock(
  className: string,
  entries: ScheduleEntry[],
  periods: number,
  eveningStartPeriod?: number | null,
) {
  const eveningStart = eveningStartPeriod ?? periods + 1
  const headers = ['节\\周', '一', '二', '三', '四', '五', '单六', '双六']
  const lines = [`班级：${className}`, headers.join(',')]

  for (let period = 1; period <= periods; period += 1) {
    const row = [
      String(period),
      ...DAY_KEYS.map((day) => {
        const text = entries
          .filter(
            (item) =>
              item.weekday === day.weekday
              && item.period === period
              && matchesParity(item.week_parity, day.parity),
          )
          .map((item) => item.subject_name || '')
          .filter(Boolean)
          .join('·')
        return `"${text.replace(/"/g, '""')}"`
      }),
    ]
    lines.push(row.join(','))
  }

  for (const evening of [
    { label: `${eveningStart}`, parity: 'odd' as const },
    { label: `${eveningStart}双`, parity: 'even' as const },
  ]) {
    const row = [
      evening.label,
      ...DAY_KEYS.map((day) => {
        if (day.weekday === 6 && day.parity !== evening.parity) {
          return '""'
        }
        const text = entries
          .filter(
            (item) =>
              item.weekday === day.weekday
              && item.period >= eveningStart
              && matchesParity(item.week_parity, evening.parity),
          )
          .map((item) => item.subject_name || '')
          .filter(Boolean)
          .join('·')
        return `"${text.replace(/"/g, '""')}"`
      }),
    ]
    lines.push(row.join(','))
  }
  return lines.join('\n')
}

function triggerCsvDownload(content: string, fileName: string) {
  const bom = '\uFEFF'
  const blob = new Blob([bom + content], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName.replace(/[\\/:*?"<>|]/g, '_')
  anchor.click()
  URL.revokeObjectURL(url)
}

/** 导出与手排 Excel 同列结构：一～五 + 单六/双六，晚自习单双两行。 */
export function downloadClassTimetableCsv(
  className: string,
  entries: ScheduleEntry[],
  periods: number,
  eveningStartPeriod?: number | null,
) {
  triggerCsvDownload(
    buildClassCsvBlock(className, entries, periods, eveningStartPeriod),
    `${className}_课表.csv`,
  )
}

/** 导出多个班级到同一个 CSV（班级之间空一行）。 */
export function downloadAllClassTimetablesCsv(
  items: Array<{ className: string; entries: ScheduleEntry[] }>,
  periods: number,
  eveningStartPeriod?: number | null,
  fileName = '全部班级_课表.csv',
) {
  const blocks = items.map((item) =>
    buildClassCsvBlock(item.className, item.entries, periods, eveningStartPeriod),
  )
  triggerCsvDownload(blocks.join('\n\n'), fileName)
}
