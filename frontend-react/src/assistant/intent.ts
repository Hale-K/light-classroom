/** 老师原话意图：先判定「要干什么」，再决定工具。 */

import { parseRuleGuide, type RuleGuide } from './ruleGuide.ts'

export type PrepSlot = { subject: string; weekday: string; periods: number[] }

export type ConsecutiveHint = { subject: string; weekly?: number }

export type TeacherIntent =
  | { name: 'prep_forbidden'; slots: PrepSlot[] }
  | { name: 'consecutive'; hint: ConsecutiveHint }
  | { name: 'rule_pack' }
  | { name: 'rule_add'; guide: RuleGuide }
  | { name: 'other' }

const SUBJECTS = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理'] as const

const WEEKDAY: Record<string, string> = {
  一: '周一',
  二: '周二',
  三: '周三',
  四: '周四',
  五: '周五',
  六: '周六',
  日: '周日',
  天: '周日',
}

/** 本校规则组默认的九科备课时段（R01-01…09）。口头没列全时用这张表对照。 */
export const DEFAULT_PREP: PrepSlot[] = [
  { subject: '语文', weekday: '周一', periods: [6, 7] },
  { subject: '英语', weekday: '周二', periods: [6, 7] },
  { subject: '数学', weekday: '周三', periods: [6, 7] },
  { subject: '物理', weekday: '周二', periods: [3, 4] },
  { subject: '化学', weekday: '周五', periods: [3, 4] },
  { subject: '生物', weekday: '周四', periods: [3, 4] },
  { subject: '政治', weekday: '周三', periods: [4, 5] },
  { subject: '历史', weekday: '周五', periods: [6, 7] },
  { subject: '地理', weekday: '周四', periods: [6, 7] },
]

const SLOT_RE = new RegExp(
  `(${SUBJECTS.join('|')})\\s*(星期[一二三四五六日天]|周[一二三四五六日天]|礼拜[一二三四五六日天])\\s*[：:]\\s*([0-9]+(?:\\s*[、,，]\\s*[0-9]+)*)\\s*节?`,
  'g',
)

export function parsePrepSlots(text: string): PrepSlot[] {
  const out: PrepSlot[] = []
  const seen = new Set<string>()
  for (const m of text.matchAll(SLOT_RE)) {
    const subject = m[1]
    const day = WEEKDAY[m[2].slice(-1)]
    const periods = m[3]
      .split(/[、,，\s]+/)
      .map((n) => Number(n))
      .filter((n) => n > 0)
    if (!day || !periods.length) continue
    const key = `${subject}-${day}-${periods.join(',')}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ subject, weekday: day, periods })
  }
  return out
}

export function parseConsecutive(text: string): ConsecutiveHint | null {
  if (!/连堂|连着上/.test(text)) return null
  const subject = SUBJECTS.find((name) => text.includes(name))
  if (!subject) return null
  const weekly = text.match(/(\d{1,2})\s*(?:个)?(?:课时|节)/)
  return { subject, weekly: weekly ? Number(weekly[1]) : undefined }
}

function looksLikePrepForbidden(text: string): boolean {
  if (parsePrepSlots(text).length >= 1) return true
  if (/备课时间|备课时段|不排相应课程/.test(text)) return true
  if (/排课要求/.test(text) && /备课/.test(text)) return true
  return false
}

/** 整包 21 条才走 rule_pack；单列备课不走。 */
export function looksLikeRulePack(text: string): boolean {
  if (/这些规则|21条/.test(text)) return true
  if (/对课/.test(text) && /(物理|历史|单双周)/.test(text)) return true
  if (/周六晚/.test(text) && /班主任/.test(text)) return true
  return text.length > 120 && /备课/.test(text) && /晚课/.test(text)
}

export function classifyTeacherIntent(text: string): TeacherIntent {
  const t = text.trim()
  const consecutive = parseConsecutive(t)
  if (consecutive) return { name: 'consecutive', hint: consecutive }
  const add = parseRuleGuide(t)
  if (add) return { name: 'rule_add', guide: add }
  if (looksLikePrepForbidden(t) && !looksLikeRulePack(t)) {
    const parsed = parsePrepSlots(t)
    return { name: 'prep_forbidden', slots: parsed.length ? parsed : DEFAULT_PREP }
  }
  if (looksLikeRulePack(t)) return { name: 'rule_pack' }
  if (looksLikePrepForbidden(t)) {
    const parsed = parsePrepSlots(t)
    return { name: 'prep_forbidden', slots: parsed.length ? parsed : DEFAULT_PREP }
  }
  return { name: 'other' }
}
