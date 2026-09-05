/** 标准方案 10 科 30 节，多出的节加到本校未占用科目或体育/语文。 */

export const STANDARD_HOURS: Array<[string, number]> = [
  ['语文', 5],
  ['数学', 5],
  ['英语', 5],
  ['物理', 3],
  ['化学', 3],
  ['生物', 2],
  ['政治', 2],
  ['历史', 2],
  ['地理', 2],
  ['体育', 1],
]

export type HourRow = { name: string; periods: number; subject_id: number | null; from_standard: boolean }

export type HoursDraft = {
  year: string
  term: string
  classIds: number[]
  rows: Array<{ subject_id: number; name: string; periods: number }>
}

export function parseWeeklyTotal(text: string): number | null {
  const a = text.match(/(?:每周|一周)[^\d]{0,8}(\d{1,2})/)
  if (a) return Number(a[1])
  const b = text.match(/(?:安排|怎么分|怎么排|拆)[^\d]{0,8}(\d{1,2}).{0,4}(?:节|课时)/)
  if (b) return Number(b[1])
  const c = text.match(/(\d{1,2})\s*(?:个)?课时/)
  if (c) return Number(c[1])
  return null
}

export function isHoursPlan(text: string): boolean {
  const n = parseWeeklyTotal(text)
  if (n == null || n < 8 || n > 60) return false
  return /安排|怎么|拆|分到|学科|科目|课时/.test(text)
}

export function allocateHours(
  target: number,
  subjects: Array<{ id: number; name: string; course_type?: string }>,
): { rows: HourRow[]; notes: string[] } {
  const notes: string[] = []
  const rows: HourRow[] = []
  const used = new Set<number>()
  let sum = 0
  for (const [label, n] of STANDARD_HOURS) {
    const hit = subjects.find((s) => s.name === label || s.name.includes(label))
    if (!hit) {
      notes.push(`科目库没有「${label}」，这 ${n} 节并入待分配`)
      continue
    }
    rows.push({ name: hit.name, periods: n, subject_id: hit.id, from_standard: true })
    used.add(hit.id)
    sum += n
  }
  let rest = target - sum
  const bump = (id: number | null, name: string, add: number) => {
    const row = rows.find((r) => (id != null && r.subject_id === id) || r.name === name)
    if (row) {
      row.periods += add
      return
    }
    rows.push({ name, periods: add, subject_id: id, from_standard: false })
  }
  if (rest < 0) {
    notes.push(`标准方案已 ${sum} 节，高于目标 ${target}，从地理/生物往下减，语数英不低于 4`)
    for (const name of ['地理', '生物', '历史', '政治', '体育', '化学', '物理']) {
      const row = rows.find((r) => r.name.includes(name))
      if (!row) continue
      const take = Math.min(row.periods - (['语文', '数学', '英语'].some((x) => row.name.includes(x)) ? 4 : 1), -rest)
      if (take <= 0) continue
      row.periods -= take
      rest += take
      if (rest >= 0) break
    }
  }
  if (rest > 0) {
    const extras = subjects.filter((s) => !used.has(s.id) && s.course_type !== 'activity')
    if (extras.length) {
      bump(extras[0].id, extras[0].name, rest)
      notes.push(`多出 ${rest} 节加在「${extras[0].name}」（本校标准方案外的科目）`)
      rest = 0
    } else {
      const pe = rows.find((r) => r.name.includes('体育'))
      if (pe && rest >= 1) {
        pe.periods += 1
        rest -= 1
        notes.push('体育由 1 改为 2')
      }
      if (rest > 0) {
        const yu = rows.find((r) => r.name.includes('语文'))
        if (yu) {
          yu.periods += rest
          notes.push(`其余 ${rest} 节加在语文，请按校本改掉`)
          rest = 0
        }
      }
    }
  }
  const total = rows.reduce((a, r) => a + r.periods, 0)
  if (total !== target) notes.push(`加总 ${total}，与目标 ${target} 不一致，请人工改课时表`)
  return { rows, notes }
}
