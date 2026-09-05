export type RuleGuide = {
  family: string
  template: string
  target: string
  action: string
  weekday: string
  periods: string
  note?: string
}

const CN: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
}

function parsePeriods(text: string): number[] {
  const out: number[] = []
  const seen = new Set<number>()
  const add = (n: number) => {
    if (n > 0 && n <= 20 && !seen.has(n)) {
      seen.add(n)
      out.push(n)
    }
  }
  for (const m of text.matchAll(/第\s*([0-9]+|[一二三四五六七八九十]+)\s*节/g)) {
    const raw = m[1]
    add(/^\d+$/.test(raw) ? Number(raw) : CN[raw] || 0)
  }
  if (!out.length) {
    const m = text.match(/([0-9]+|[一二三四五六七八九十]+)节/)
    if (m) {
      const raw = m[1]
      add(/^\d+$/.test(raw) ? Number(raw) : CN[raw] || 0)
    }
  }
  return out
}

function periodLabel(periods: number[]): string {
  if (!periods.length) return '未指定节次，请自己勾'
  return `第${periods.join('、')}节`
}

/** 把「班主任第五节不能排」对到建立规则里的组件名和填法。 */
export function parseRuleGuide(text: string): RuleGuide | null {
  const t = text.trim()
  if (!t) return null
  const periods = parsePeriods(t)
  const forbid = /不能排|不排|禁排/.test(t)
  const requireRole = /必须|只能/.test(t) && /班主任/.test(t)

  if (/班主任/.test(t) && requireRole && !forbid) {
    return {
      family: '课位规则',
      template: '课位教师角色',
      target: '全年级各班 · 本班班主任',
      action: '必须安排班主任',
      weekday: /周六/.test(t) ? '周六' : '按你要的星期勾',
      periods: periodLabel(periods.length ? periods : [10]),
      note: '这是「必须由班主任上」，不是禁排。',
    }
  }

  if (/班主任/.test(t) && forbid) {
    return {
      family: '教师规则',
      template: '教师课位禁排',
      target: '班主任',
      action: '禁止排课',
      weekday: /周[一二三四五六]/.test(t) ? (t.match(/周[一二三四五六]/)?.[0] ?? '全周') : '全周',
      periods: periodLabel(periods),
      note: '不要选「课位禁排」（那是按学科挡课），也不要选「课位教师角色」（那是必须班主任上）。',
    }
  }

  return null
}

export function ruleGuideCopy(guide: RuleGuide, onRules: boolean): { report: string; advice: string } {
  const where = onRules
    ? '当前就在规则工作台。'
    : '先到排课「建立规则」。'
  return {
    report: `${where}用组件「${guide.template}」。`,
    advice: [
      '操作：',
      '1. 点「规则明细」右上角 +',
      `2. 在「${guide.family}」里选「${guide.template}」`,
      `3. 作用对象：${guide.target}`,
      `4. 规则动作：${guide.action}`,
      `5. 星期：${guide.weekday}；节次：${guide.periods}`,
      '6. 硬约束，点保存',
      guide.note || '',
    ]
      .filter(Boolean)
      .join('\n'),
  }
}
