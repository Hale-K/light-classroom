import type { SchedulingGridConfig, SchedulingResources, SchedulingRuleDefinition } from '../../types/index.ts'

export interface RuleCheckIssue {
  level: 'error' | 'warning'
  message: string
  ruleIds: string[]
  kind?: 'duplicate' | 'redundant' | 'overlap' | 'conflict' | 'incomplete'
  context?: string
  suggestions?: string[]
}
export interface RuleCheckSlot {
  weekday: number
  period: number
  week_parity: 'odd' | 'even'
  kind: 'regular' | 'evening'
}

export const ruleWeekParity = (cycle: string): 'all' | 'odd' | 'even' =>
  cycle === '单周' ? 'odd' : cycle === '双周' ? 'even' : 'all'

export function configuredRuleSlots(grid?: SchedulingGridConfig): RuleCheckSlot[] | undefined {
  if (!grid?.configured) return undefined
  const slots: RuleCheckSlot[] = []
  for (let weekday = 1; weekday <= 7; weekday++) {
    for (const leg of ['odd', 'even'] as const) {
      const regular = grid.daily_periods[weekday - 1] || 0
      const evening = grid.enable_evening ? (leg === 'odd' ? grid.evening_daily_periods_odd : grid.evening_daily_periods_even)[weekday - 1] || 0 : 0
      const eveningStart = grid.evening_start_period ?? grid.periods_per_day + 1
      const periods = [...Array.from({ length: regular }, (_, i) => i + 1), ...Array.from({ length: evening }, (_, i) => eveningStart + i)]
      for (const period of periods) {
        const override = grid.slot_overrides?.find(s => s.weekday === weekday && s.period === period && s.week_parity === leg)
        if (override?.slot_type === 'disabled') continue
        slots.push({ weekday, period, week_parity: leg, kind: override ? (override.slot_type === 'evening' ? 'evening' : 'regular') : period >= eveningStart ? 'evening' : 'regular' })
      }
    }
  }
  return slots
}

const coversSlot = (rule: SchedulingRuleDefinition, slot: RuleCheckSlot) => {
  if (rule.period_scope !== 'any' && rule.period_scope !== slot.kind) return false
  const specific = rule.params.forbidden_slots
  if (Array.isArray(specific) && specific.length) {
    return specific.some(s => s.weekday === slot.weekday && Array.isArray(s.periods) && s.periods.includes(slot.period))
  }
  return (!rule.weekdays.length || rule.weekdays.includes(slot.weekday)) &&
    (!rule.periods.length || rule.periods.includes(slot.period)) &&
    (rule.period_scope === 'any' || rule.period_scope === slot.kind)
}
const stable = (value: unknown): string => {
  if (Array.isArray(value)) return JSON.stringify(value.map(stable).sort())
  if (value && typeof value === 'object') return JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, stable(v)]))
  return JSON.stringify(value) ?? ''
}

const isBan = (r: SchedulingRuleDefinition) => ['slot_forbidden', 'teacher_forbidden_slots'].includes(r.code)
const isAllowance = (r: SchedulingRuleDefinition) => r.code === 'subject_allowed_slots' ||
  (r.code === 'subject_prefer_early_periods' && Number(r.params.max_outside ?? 0) === 0 && r.periods.length > 0)
const activeAt = (r: SchedulingRuleDefinition, mode: 'admin' | 'walk', leg: 'odd' | 'even') =>
  (!r.schedule_scope || r.schedule_scope === 'all' || r.schedule_scope === mode) && (r.week_parity === 'all' || r.week_parity === leg)
const subset = <T,>(a: T[], b: T[]) => a.every(x => b.includes(x))
const targetContains = (a: SchedulingRuleDefinition, b: SchedulingRuleDefinition) =>
  a.target.type === 'global' || (a.target.type === b.target.type && subset(b.target.ids, a.target.ids))
const targetOverlaps = (a: SchedulingRuleDefinition, b: SchedulingRuleDefinition) =>
  a.target.type === 'global' || b.target.type === 'global' || (a.target.type === b.target.type && a.target.ids.some(id => b.target.ids.includes(id)))

/** 确定性配置检查；任教关系只用于行政班，走班学生与资源容量交给排课求解。 */
export function inspectRuleConfiguration(rules: SchedulingRuleDefinition[], slots?: RuleCheckSlot[], resources?: SchedulingResources): RuleCheckIssue[] {
  const issues: RuleCheckIssue[] = []
  const enabled = rules.filter(r => r.enabled)
  const reported = new Set<string>()
  const add = (issue: RuleCheckIssue) => {
    const key = stable([issue.kind, [...new Set(issue.ruleIds)].sort(), issue.context])
    if (reported.has(key)) return
    reported.add(key)
    issues.push({ ...issue, ruleIds: [...new Set(issue.ruleIds)] })
  }
  const conflict = (participants: SchedulingRuleDefinition[], message: string, context: string, suggestions: string[]) =>
    add({ level: participants.every(r => r.priority === 'hard') ? 'error' : 'warning', kind: 'conflict', ruleIds: participants.map(r => r.id), message, context, suggestions })
  const seen = new Map<string, SchedulingRuleDefinition>()
  for (const rule of enabled) {
    if (rule.code === 'manual_review') {
      const disabled = Array.isArray(rule.params.disabled_teacher_names)
        ? rule.params.disabled_teacher_names.filter((name): name is string => typeof name === 'string' && Boolean(name)).slice(0, 8) : []
      add({ level: 'error', kind: 'incomplete', ruleIds: [rule.id],
        message: disabled.length ? `「${rule.title}」引用的教师${disabled.join('、')}账号已停用，无法应用这条规则。` : `「${rule.title}」尚未识别有效对象或要求，请补全配置。`,
        suggestions: disabled.length ? ['到人员账号核对教师状态；确需继续任教时，由有权限的人员启用账号。', '如果教师已离岗，请调整规则对象或停用这条规则；原课位配置可保留。'] : ['选择有效的学科、教师或班级，补全规则要求。'] })
    }
    const { id: _id, title: _title, ...configuration } = rule
    // 编辑入口和文案不改变规则语义；具体禁排课位与笛卡尔积禁排采用同一规范形式。
    const { source_operator: _operator, forbidden_slots: _specific, ...params } = rule.params
    const normalizedBan = isBan(rule) && slots ? {
      ...configuration, code: 'slot_forbidden', weekdays: [], periods: [], params,
      covered: slots.filter(s => coversSlot(rule, s)).map(s => `${s.weekday}/${s.period}/${s.kind}/${s.week_parity}`),
    } : { ...configuration, params: { ...rule.params, source_operator: undefined } }
    const key = stable(normalizedBan)
    const previous = seen.get(key)
    if (previous) add({ level: 'warning', kind: 'duplicate', ruleIds: [previous.id, rule.id], message: `「${rule.title}」与「${previous.title}」实际要求相同，重复配置不会增加约束。`, suggestions: ['保留一条，另一条停用或删除。先确认备注是否需要保留。'] })
    else seen.set(key, rule)
    if (['subject_consecutive', 'teacher_consecutive'].includes(rule.code) && rule.weekdays.length && Number(rule.params.minimum_days) > rule.weekdays.length) {
      conflict([rule], `「${rule.title}」要求 ${rule.params.minimum_days} 天连堂，但只选择了 ${rule.weekdays.length} 天。`, '连堂天数', ['减少至少天数，或增加候选星期。'])
    }
  }
  if (!slots) return issues
  // 兼容交叉与真正矛盾分开：两条上限取较小值，不是互相冲突。
  for (let i = 0; i < enabled.length; i++) for (let j = i + 1; j < enabled.length; j++) {
    const a = enabled[i], b = enabled[j]
    if (!targetOverlaps(a, b)) continue
    if ([a.code, b.code].includes('subject_prefer_early_periods') && [a.code, b.code].includes('subject_gap_fill_late_periods') &&
      (['admin', 'walk'] as const).some(m => (['odd', 'even'] as const).some(leg => activeAt(a, m, leg) && activeAt(b, m, leg)))) {
      add({ level: 'warning', kind: 'overlap', ruleIds: [a.id, b.id], message: '同一学科同时设置了选定节次偏好和后段补空策略，职责交叉。后段补空带有回退条件，因此不能直接认定为重复或无解。', suggestions: ['如果只想表达“优先排在某些节次”，保留一个节次偏好即可。', '只有需要“后段有空位时先补后段”的条件行为，才保留后段补空；核对另一条偏好是否仍有必要。'] })
    }
    const common = slots.filter(s => coversSlot(a, s) && coversSlot(b, s) &&
      (['admin', 'walk'] as const).some(m => activeAt(a, m, s.week_parity) && activeAt(b, m, s.week_parity)))
    if (!common.length) continue
    if (reported.has(stable(['duplicate', [a.id, b.id].sort(), undefined]))) continue
    if (a.code === 'teacher_daily_limit' && b.code === a.code && a.priority === b.priority) {
      add({ level: 'warning', kind: 'overlap', ruleIds: [a.id, b.id], message: `两条每日上限作用范围重叠；重叠教师按每天最多 ${Math.min(Number(a.params.max_lessons_per_day), Number(b.params.max_lessons_per_day))} 节执行，属于兼容交叉。`, suggestions: ['如属于有意设置的更严格要求，可保留；否则合并对象和上限，减少维护负担。'] })
    } else if (((isBan(a) && isBan(b)) || (a.code === 'subject_allowed_slots' && b.code === a.code)) && a.priority === b.priority) {
      const signature = (r: SchedulingRuleDefinition) => slots.flatMap(s => (['admin', 'walk'] as const).filter(m => activeAt(r, m, s.week_parity) && coversSlot(r, s)).map(m => `${m}/${s.week_parity}/${s.weekday}/${s.period}/${s.kind}`))
      const sa = signature(a), sb = signature(b)
      const redundant = isBan(a) ? (targetContains(a, b) && subset(sb, sa)) || (targetContains(b, a) && subset(sa, sb))
        : (targetContains(a, b) && subset(sa, sb)) || (targetContains(b, a) && subset(sb, sa))
      add({ level: 'warning', kind: redundant ? 'redundant' : 'overlap', ruleIds: [a.id, b.id], message: redundant ? '两条规则的部分职责完全被另一条覆盖，属于冗余约束。' : `两条规则范围部分重叠；${isBan(a) ? '禁排课位合并执行' : '允许课位取共同范围'}。范围重叠本身不代表冲突。`, suggestions: ['核对对象、课表范围和单双周；只在完全覆盖时停用冗余规则，否则保留各自独立部分。'] })
    }
  }
  for (const timetable of ['admin', 'walk'] as const) for (const leg of ['odd', 'even'] as const) {
    const active = enabled.filter(r => activeAt(r, timetable, leg))
    const hard = active.filter(r => r.priority === 'hard')
    const available = slots.filter(s => s.week_parity === leg)
    const context = `${timetable === 'admin' ? '行政课表' : '走班课表'} · ${leg === 'odd' ? '单周' : '双周'}`
    const targets = (r: SchedulingRuleDefinition, type: string, id: number) => r.target.type === 'global' || (r.target.type === type && r.target.ids.includes(id))
    const teacherIds = (r: SchedulingRuleDefinition) => r.target.type === 'teacher' ? r.target.ids : r.target.type === 'subject' && timetable === 'admin'
      ? [...new Set(resources?.assignments.filter(a => r.target.ids.includes(a.subject_id) && a.teacher_id != null).map(a => a.teacher_id!) || [])] : []
    const name = (type: 'teachers' | 'subjects' | 'classes', id: number) => resources?.[type].find(r => r.id === id)?.name || `${type === 'teachers' ? '教师' : type === 'subjects' ? '学科' : '班级'} ${id}`
    const checkSubject = (subjectId: number, teacherId?: number | null, classId?: number) => {
      const restrictions = active.filter(r => isAllowance(r) && targets(r, 'subject', subjectId))
      if (!restrictions.length) return
      const blockers = active.filter(r => (isBan(r) && (!r.params.own_head_class_only || (classId != null && resources?.classes.some(c => c.id === classId && c.head_teacher_id === teacherId))) && (targets(r, 'subject', subjectId) || (teacherId != null && targets(r, 'teacher', teacherId)) || (classId != null && targets(r, 'class', classId)))) ||
        (r.code === 'class_allowed_subjects' && classId != null && targets(r, 'class', classId) && (r.params.forbid_all || !(r.params.allowed_subject_ids as number[] || []).includes(subjectId))))
      const run = (pool: SchedulingRuleDefinition[]) => {
        const limits = restrictions.filter(r => pool.includes(r))
        if (!limits.length) return false
        const bans = blockers.filter(r => pool.includes(r))
        const candidates = available.filter(s => limits.every(r => coversSlot(r, s)))
        if (candidates.some(s => !bans.some(r => coversSlot(r, s)))) return false
        const relevant = bans.filter(r => candidates.some(s => coversSlot(r, s)))
        const targetLabel = `${classId != null ? name('classes', classId) + ' · ' : ''}${name('subjects', subjectId)}${teacherId != null ? ' · ' + name('teachers', teacherId) : ''}`
        conflict([...limits, ...relevant], `${targetLabel}：${relevant.length ? `允许课位已被「${relevant.map(r => r.title).join('、')}」全部禁排或排除` : `「${limits.map(r => r.title).join('、')}」没有共同可用课位`}。`, `${context} · ${targetLabel}`, ['扩大“仅允许”的星期或节次，保留至少一个可用课位。', '若禁排来自真实会议、休假等限制，应保留禁排，调整其他允许范围；如只是偏好，可改为“尽量满足”。'])
        return true
      }
      if (!run(hard)) run(active)
    }
    for (const subjectId of new Set(active.filter(isAllowance).flatMap(r => r.target.ids))) {
      checkSubject(subjectId)
      if (timetable === 'admin') for (const a of resources?.assignments.filter(a => a.subject_id === subjectId && a.weekly_periods > 0) || []) checkSubject(subjectId, a.teacher_id, a.class_id)
    }
    for (const full of active.filter(r => timetable === 'admin' && r.code === 'class_gap_free' && !r.params.trailing_empty)) {
      const classIds = full.target.type === 'class' ? full.target.ids : resources?.classes.map(c => c.id) || []
      for (const classId of classIds) {
        const banned = active.filter(r => isBan(r) && targets(r, 'class', classId))
        const required = available.filter(s => s.kind === 'regular' && s.period <= 7 && (!full.weekdays.length || full.weekdays.includes(s.weekday)))
        const relevant = banned.filter(r => required.some(s => coversSlot(r, s)))
        for (const ban of relevant) {
          const s = required.find(s => coversSlot(ban, s))!
          conflict([full, ban], `${name('classes', classId)}周${'一二三四五六日'[s.weekday - 1]}第 ${s.period} 节既要求有课，又被禁止排课。`, `${context} · ${name('classes', classId)}`, ['如果该时段确实不上课，缩小“班级无空堂”的日期范围，或使用允许末尾空节的连续方式。', '如果禁排是误设，调整禁排课位；不要为填满课表随意增加学科课时。'])
        }
      }
    }
    if (timetable === 'admin') for (const role of active.filter(r => r.code === 'slot_teacher_role_required')) for (const cls of resources?.classes.filter(c => targets(role, 'class', c.id)) || []) {
      if (!cls.head_teacher_id) {
        add({ level: 'warning', kind: 'incomplete', ruleIds: [role.id], context: `${context} · ${cls.name}`, message: `${cls.name}尚未配置班主任，无法确认班主任课位是否可排。`, suggestions: ['先在班级管理配置班主任，并确认其任教关系。'] }); continue
      }
      const relevant = active.filter(r => isBan(r) && (targets(r, 'teacher', cls.head_teacher_id!) || targets(r, 'class', cls.id)) && available.some(s => coversSlot(role, s) && coversSlot(r, s)))
      for (const ban of relevant) conflict([role, ban], `${cls.name}要求班主任 ${name('teachers', cls.head_teacher_id)} 在指定课位授课，但该课位被「${ban.title}」禁排。`, `${context} · ${cls.name}`, ['将班主任必上课位调整到其可用时间，或核对禁排是否误设。', '核对班主任是否有本班任教科目与足够课时。'])
    }
    for (const minimum of active.filter(r => ['teacher_period_minimum', 'teacher_consecutive', 'subject_consecutive'].includes(r.code))) {
      const ids = minimum.code === 'subject_consecutive' ? minimum.target.ids : teacherIds(minimum)
      for (const id of ids) {
        const type = minimum.code === 'subject_consecutive' ? 'subject' : 'teacher'
        const bans = hard.filter(r => isBan(r) && !r.params.own_head_class_only && targets(r, type, id) && available.some(s => coversSlot(minimum, s) && coversSlot(r, s)))
        const caps = type === 'teacher' ? hard.filter(r => r.code === 'teacher_daily_limit' && teacherIds(r).includes(id) && available.some(s => coversSlot(minimum, s) && (!r.weekdays.length || r.weekdays.includes(s.weekday)))) : []
        const allowed = type === 'subject' ? hard.filter(r => isAllowance(r) && targets(r, type, id)) : []
        const candidates = available.filter(s => coversSlot(minimum, s) && !bans.some(r => coversSlot(r, s)) && allowed.every(r => coversSlot(r, s)))
        const byDay = [...new Set(candidates.map(s => s.weekday))].map(day => {
          const daySlots = candidates.filter(s => s.weekday === day)
          const dayCaps = caps.filter(r => !r.weekdays.length || r.weekdays.includes(day)).map(r => Number(r.params.max_lessons_per_day))
          const limit = Math.min(daySlots.length, ...dayCaps)
          let longest = 0, length = 0, prev = -2, kind = ''
          for (const s of daySlots.slice().sort((a, b) => a.period - b.period)) { length = s.period === prev + 1 && s.kind === kind ? length + 1 : 1; longest = Math.max(longest, length); prev = s.period; kind = s.kind }
          return { capacity: limit, block: Math.min(longest, limit) }
        })
        const demand = Number(minimum.params.minimum_lessons || 0)
        const block = Number(minimum.params.minimum_block_length || 2), days = Number(minimum.params.minimum_days || 1)
        const capacity = byDay.reduce((n, d) => n + d.capacity, 0)
        const feasibleDays = byDay.filter(d => d.block >= block).length
        if (minimum.code === 'teacher_period_minimum' ? capacity >= demand : feasibleDays >= days) continue
        conflict([minimum, ...bans, ...caps, ...allowed], minimum.code === 'teacher_period_minimum'
          ? `${name('teachers', id)}要求至少 ${demand} 节，但所选课位在禁排和每日上限之后最多容纳 ${capacity} 节。`
          : `「${minimum.title}」要求至少 ${days} 天连续 ${block} 节，当前可用课位与每日上限最多支持 ${feasibleDays} 天。`, `${context} · ${name(type === 'teacher' ? 'teachers' : 'subjects', id)}`, ['增加可用日期或节次，或降低至少课时、连堂长度、连堂天数。', '如果每日上限允许调整，可适当提高；真实禁排应保留。偏好性连堂可改为“尽量满足”。'])
      }
    }
  }
  return issues.sort((a, b) => Number(b.level === 'error') - Number(a.level === 'error'))
}
