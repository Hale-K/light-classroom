import { authApi, facilityApi, orgApi, schedulingApi, teacherProfilesApi } from '@/api'
import { allocateHours, type HoursDraft } from '@/assistant/hoursPlan'
import type { ConsecutiveHint, PrepSlot } from '@/assistant/intent'
import { placeLabel, schedTab } from '@/assistant/place'
import { ruleGuideCopy, type RuleGuide } from '@/assistant/ruleGuide'
import { assistLog } from '@/assistant/trace'
import { pageGuidanceText } from '@/assistant/page-guidance'

export type AssistantTool = 'openScheduling' | 'checkTeachers' | 'checkSettings' | 'guideGrade' | 'howToUse' | 'howToUseScheduling' | 'countSubjectTeachers' | 'proposeHours' | 'go' | 'explainRulePack' | 'executeHours' | 'nextStep' | 'pageGuide'

export type JumpLink = { label: string; path: string }

export type ToolExtra = {
  grade?: string
  subject?: string
  weekly?: number
  hoursDraft?: HoursDraft
  prepSlots?: PrepSlot[]
  consecutive?: ConsecutiveHint
  ruleGuide?: RuleGuide
  here?: string
  traceId?: string
}

export type ToolResult = {
  path: string
  report: string
  hoursDraft?: HoursDraft
  awaitRules?: boolean
  jumps?: JumpLink[]
  advice?: string
}

const GRADE_ALIASES: Record<string, string> = {
  高一: '高一',
  高二: '高二',
  高三: '高三',
  高1: '高一',
  高2: '高二',
  高3: '高三',
}

export function parseGradeLabel(text: string): string | null {
  const hit = text.match(/高[一二三123]/)
  if (!hit) return null
  return GRADE_ALIASES[hit[0]] || null
}

export function isGradeSchedule(text: string): boolean {
  const grade = parseGradeLabel(text)
  if (!grade) return false
  return /排|课表|课时|课|下一步|该干什么|怎么办/.test(text)
}

const SUBJECT_HINTS = ['语文', '数学', '英语', '物理', '化学', '生物', '政治', '历史', '地理', '体育', '音乐', '美术', '心理']

export function parseSubjectLabel(text: string): string | null {
  return SUBJECT_HINTS.find((name) => text.includes(name)) || null
}

export function isCountSubjectTeachers(text: string): boolean {
  if (!parseSubjectLabel(text)) return false
  return /多少|几个|几位|有哪些|是谁/.test(text) && /老师|教师|任教/.test(text)
}

export function isRulePack(text: string): boolean {
  if (/这些规则|21条|备课时间/.test(text)) return true
  if (/备课/.test(text) && /(语文|英语|数学|物理|化学|时段)/.test(text)) return true
  if (/对课/.test(text) && /(物理|历史|单双周)/.test(text)) return true
  if (/周六晚/.test(text) && /班主任/.test(text)) return true
  return text.length > 120 && /备课/.test(text) && /晚课/.test(text)
}

async function yearGridLine() {
  const years = await authApi.academicYears()
  const year = years.current_academic_year
  const term = years.current_term || '1'
  let gridLine = '网格未读到（先在系统设置核对学年学期）'
  if (year) {
    try {
      const grid = await schedulingApi.gridConfig({ academic_year: year, term })
      gridLine = `网格 ${grid.days} 天 × ${grid.periods_per_day} 节${grid.enable_evening ? '，含晚自习' : ''}`
    } catch {
      gridLine = '网格尚未配置，请先到排课「课位结构」保存'
    }
  }
  return { year: year || '未设', term, gridLine }
}

function subjectCovered(name: string, names: Set<string>): boolean {
  for (const item of names) {
    if (item === name || item.includes(name) || name.includes(item)) return true
  }
  return false
}

export type ThinkFn = (line: string) => void

async function checkPrepPreconditions(
  slots: PrepSlot[],
  think?: ThinkFn,
): Promise<{ ok: true; year: string; term: string; gridLine: string } | { ok: false; path: string; report: string }> {
  think?.('核对本校学年和课位')
  const years = await authApi.academicYears()
  const year = years.current_academic_year
  const term = years.current_term || '1'
  if (!year) {
    return { ok: false, path: '/settings', report: '还没有当前学年。请先到系统设置核对学年学期，再配备课时段。' }
  }
  let periodsPerDay = 0
  let gridLine = '网格未配置'
  try {
    const grid = await schedulingApi.gridConfig({ academic_year: year, term })
    periodsPerDay = grid.periods_per_day
    gridLine = `网格 ${grid.days} 天 × ${grid.periods_per_day} 节${grid.enable_evening ? '，含晚自习' : ''}`
  } catch {
    return { ok: false, path: '/scheduling?tab=slots', report: '课位结构还没保存，备课时段对不上第几节。请先到排课「课位结构」保存网格。' }
  }
  const needMax = Math.max(0, ...slots.flatMap((s) => s.periods))
  if (needMax > periodsPerDay) {
    return {
      ok: false,
      path: '/scheduling?tab=slots',
      report: `网格每天只有 ${periodsPerDay} 节，备课时段写到第 ${needMax} 节。请先改课位结构，再配禁排。`,
    }
  }
  const resources = await schedulingApi.resources()
  if (!resources.classes.length) {
    return { ok: false, path: '/classes', report: '还没有行政班。请先建班，再填课时和任教，最后才是备课时段禁排。' }
  }
  think?.('核对本校课时是否已建')
  const hours = await schedulingApi.courseHours({ academic_year: year, term })
  const hourNames = new Set(
    hours.filter((h) => (h.weekday_periods || 0) > 0).map((h) => h.subject_name || ''),
  )
  think?.('核对本校任教是否已建')
  const asgNames = new Set(
    resources.assignments
      .filter((a) => a.academic_year === year && a.term === term && a.teacher_id)
      .map((a) => a.subject_name || ''),
  )
  const missingHours = slots.map((s) => s.subject).filter((name, i, all) => all.indexOf(name) === i && !subjectCovered(name, hourNames))
  const missingAsg = slots.map((s) => s.subject).filter((name, i, all) => all.indexOf(name) === i && !subjectCovered(name, asgNames))
  if (missingHours.length && missingAsg.length) {
    return {
      ok: false,
      path: '/scheduling?tab=hours',
      report: `备课禁排要先有课时和任教。现网课时缺 ${missingHours.join('、')}，任教缺 ${missingAsg.join('、')}。请先在课时管理把这些科的周节数填上，再到任教关系对老师。`,
    }
  }
  if (missingHours.length) {
    return {
      ok: false,
      path: '/scheduling?tab=hours',
      report: `任教已有。课时还缺 ${missingHours.join('、')}。请先在课时管理填这些科的周节数，再配备课时段禁排。`,
    }
  }
  if (missingAsg.length) {
    return {
      ok: false,
      path: '/scheduling?tab=assignments',
      report: `课时已有。任教还缺 ${missingAsg.join('、')}。请先在任教关系把这些科对上老师，再配备课时段禁排。`,
    }
  }
  return { ok: true, year, term, gridLine }
}

export async function runAssistantTool(
  tool: AssistantTool,
  path?: string,
  extra?: ToolExtra,
  think?: ThinkFn,
): Promise<ToolResult> {
  const tid = extra?.traceId || '-'
  assistLog(tid, `tool.${tool}`, path || '')
  const reportThinking = think
  const marked: ThinkFn = (line) => {
    assistLog(tid, line)
    reportThinking?.(line)
  }
  think = marked
  if (tool === 'pageGuide') {
    const here = (extra?.here || path || '/').split('?')[0]
    const report = pageGuidanceText(here)
    return { path: '', report: report || '请告诉我当前要处理的教务对象，我会按页面给出操作顺序。' }
  }
  if (tool === 'nextStep' && (extra?.here || '').startsWith('/campus-buildings')) {
    think?.('读取空间资源现状')
    const [overview, rooms, rules] = await Promise.all([
      facilityApi.overview(),
      facilityApi.rooms(),
      facilityApi.allocationRules(),
    ])
    const campuses = overview.stats.campus_count
    const buildings = overview.stats.building_count
    const roomCount = overview.stats.room_count
    const activeRules = rules.filter((rule) => rule.status === 'active')
    const assignedRooms = rooms.filter((room) => (room.cohort_allocations || []).length > 0)
    const boundRooms = assignedRooms.filter((room) => (room.class_assignments || []).length > 0)
    think?.(`判断阶段：${campuses} 个校区，${buildings} 栋楼宇，${roomCount} 间场室`)

    if (campuses === 0) {
      return {
        path: '',
        report: '下一步先点右上角「新增校区」。校区是楼宇和场室的上级；建好校区后，选中它再新增楼宇。当前还没有校区，所以后面的资源分配和班级划分暂时无法开始。',
      }
    }
    if (buildings === 0) {
      return {
        path: '',
        report: `下一步：\n1. 在左侧展开「学校空间」，选中已有校区。\n2. 点右上角「新增楼宇」，填写楼宇名称、编号和楼层数。\n3. 建好后选中该楼宇，再点「新增场室」。\n\n当前有 ${campuses} 个校区、0 栋楼宇、0 间场室，所以先建楼宇；资源分配规则和班级划分要等场室建好后再做。`,
      }
    }
    if (roomCount === 0) {
      return {
        path: '',
        report: `下一步选中左侧的一栋楼宇，再点右上角「新增场室」。填写楼层、容量、场室类型，并确认是否可用于排课、排考或会议。当前有 ${campuses} 个校区、${buildings} 栋楼宇，但还没有场室。`,
      }
    }
    if (!activeRules.length || !assignedRooms.length) {
      return {
        path: '',
        jumps: [{ label: '去资源分配规则', path: '/campus-buildings?tab=allocation' }],
        report: `空间层级已经建立：${campuses} 个校区、${buildings} 栋楼宇、${roomCount} 间场室。下一步进入「资源分配规则」，选择目标届别和资源范围，先预览匹配结果，再执行分配。当前 ${activeRules.length} 条规则生效、${assignedRooms.length} 间教室已分配。`,
      }
    }
    if (boundRooms.length < assignedRooms.length) {
      return {
        path: '',
        jumps: [{ label: '去班级划分', path: '/campus-buildings?tab=class-planning' }],
        report: `已有 ${assignedRooms.length} 间教室分配给届别，其中 ${boundRooms.length} 间已绑定行政班。下一步进入「班级划分」，为剩余 ${assignedRooms.length - boundRooms.length} 间教室生成或绑定行政班，然后到班级管理补充班主任和学生名单。`,
      }
    }
    return {
      path: '',
      jumps: [{ label: '去班级管理', path: '/classes' }],
      report: `空间资源、届别分配和班级教室绑定已经有基础数据：${campuses} 个校区、${buildings} 栋楼宇、${roomCount} 间场室，${boundRooms.length} 间已绑定班级。下一步到「班级管理」核对班主任和学生名单，再进入排课配置。`,
    }
  }
  if (tool === 'proposeHours') {
    think?.('分析意图：按周课时拆科目')
    think?.('核对本校网格容量')
    const label = extra?.grade || '高一'
    const weekly = extra?.weekly
    const years = await authApi.academicYears()
    const year = years.current_academic_year
    const term = years.current_term || '1'
    if (!year) {
      return { path: '/settings', report: '还没有当前学年。请先到系统设置核对学年学期，再来说每周多少节。' }
    }
    let dayCap = 0
    let eveCap = 0
    let gridLine = '网格未配置'
    try {
      const grid = await schedulingApi.gridConfig({ academic_year: year, term })
      dayCap = grid.days * grid.periods_per_day
      eveCap = grid.enable_evening ? grid.days : 0
      gridLine = `${grid.days} 天 × ${grid.periods_per_day} 节白班 = ${dayCap}${grid.enable_evening ? `，晚课约 ${eveCap} 格` : '，无晚自习'}`
    } catch {
      return { path: '/scheduling?tab=slots', report: '课位结构还没保存，无法对 一周总节数。请先到排课「课位结构」保存网格。' }
    }
    const target = weekly && weekly > 0 ? weekly : dayCap
    const maxCap = dayCap + eveCap
    const capNotes: string[] = [`学年 ${year} 第${term}学期。${gridLine}。你要的总额 ${target} 节。`]
    if (target > maxCap) {
      capNotes.push(`超过容量 ${maxCap}，排不下。请改课位或改总额。下面预览仍按 ${target} 拆，仅供看科目，不要写入。`)
    } else if (target !== dayCap && target !== maxCap) {
      capNotes.push(`既不等于白班 ${dayCap}，也不等于白班+晚课 ${maxCap}。请改课位或改口头总额后再写入。`)
    } else if (target === maxCap && eveCap > 0) {
      capNotes.push('总额含晚课格。下列白班科目按标准方案拆；晚课仍要在课时里按 0/0.5/1 另填，不要和白班重复加。')
    }
    const grades = await orgApi.grades()
    const grade = grades.find(
      (g) => g.name.includes(label) || (label === '高一' && g.level === 1) || (label === '高二' && g.level === 2) || (label === '高三' && g.level === 3),
    )
    const subjects = await schedulingApi.subjects()
    const { rows, notes } = allocateHours(target, subjects)
    const lines = rows.filter((r) => r.periods > 0).map((r) => `${r.name} ${r.periods}`)
    const resources = grade ? await schedulingApi.resources() : { classes: [] as { id: number; grade_id?: number }[] }
    const classIds = grade
      ? resources.classes.filter((c) => Number(c.grade_id) === grade.id).map((c) => Number(c.id))
      : []
    const writable = rows.filter((r) => r.subject_id && r.periods > 0) as Array<{
      name: string
      periods: number
      subject_id: number
    }>
    const canWrite = Boolean(grade && classIds.length && writable.length && target <= maxCap)
    const hoursDraft: HoursDraft | undefined = canWrite
      ? { year, term, classIds, rows: writable.map((r) => ({ subject_id: r.subject_id, name: r.name, periods: r.periods })) }
      : undefined
    const classHint = !grade
      ? `还没有「${label}」班级，先建班。预览如下。`
      : !classIds.length
        ? `${label}还没有行政班，无法写入。`
        : target > maxCap
          ? `${label}有 ${classIds.length} 个班，但总额超过网格，不提供写入。`
          : `${label} ${classIds.length} 个班。点下方「确认写入课时」会按此表覆盖各班对应科目课时（晚课仍为 0）。`

    return {
      path: grade ? `/scheduling?tab=hours&grade=${grade.id}` : '/classes',
      hoursDraft,
      report: [
        `课时预览，尚未写入。${classHint}`,
        ...capNotes,
        `科目 ${lines.length} 门，加总 ${rows.reduce((a, r) => a + r.periods, 0)} 节：`,
        lines.join('；'),
        ...notes,
      ].join('\n'),
    }
  }
  if (tool === 'executeHours') {
    think?.('按确认写入各班课时')
    const draft = extra?.hoursDraft
    if (!draft?.classIds.length || !draft.rows.length) {
      return { path: '/scheduling?tab=hours', report: '没有可写入的课时预览。请先说每周多少节。' }
    }
    let ok = 0
    let fail = 0
    for (const classId of draft.classIds) {
      for (const row of draft.rows) {
        try {
          await schedulingApi.saveCourseHour({
            class_id: classId,
            subject_id: row.subject_id,
            academic_year: draft.year,
            term: draft.term,
            weekday_periods: row.periods,
            saturday_periods: 0,
            weekly_periods: row.periods,
            week_parity: 'all',
            evening_parity: 'all',
            evening_periods_odd: 0,
            evening_periods_even: 0,
          })
          ok += 1
        } catch {
          fail += 1
        }
      }
    }
    return {
      path: '/scheduling?tab=hours',
      report: `已写入课时：成功 ${ok} 条，失败 ${fail} 条。覆盖该年级各班对应科目的工作日节数。请再对任教、规则，最后由你点生成。`,
    }
  }
  if (tool === 'explainRulePack') {
    const guide = extra?.ruleGuide
    if (guide) {
      const onRules = schedTab(extra?.here) === 'rules'
      think?.(`判断路由：当前在${placeLabel(extra?.here)}`)
      think?.(`对到组件：${guide.template}`)
      if (onRules && typeof window !== 'undefined') {
        window.dispatchEvent(new Event('lc-assist-hint-rule-add'))
      }
      const copy = ruleGuideCopy(guide, onRules)
      return {
        path: '/scheduling?tab=rules',
        jumps: onRules ? [] : [{ label: '去建立规则', path: '/scheduling?tab=rules' }],
        report: copy.report,
        advice: copy.advice,
      }
    }
    const consecutive = extra?.consecutive
    if (consecutive) {
      const here = placeLabel(extra?.here)
      const tab = schedTab(extra?.here)
      think?.(`判断路由：当前在${here}；课时管理填节数，建立规则加连堂`)
      const hoursNeed = consecutive.weekly
        ? `把${consecutive.subject}工作日周课时填成 ${consecutive.weekly} 节（周一到周五总量，不是规则）`
        : `把${consecutive.subject}工作日周课时填够（连堂不代替节数）`
      const routeLine =
        tab === 'hours'
          ? `当前已在课时管理。请先在本页${hoursNeed}，再点「去建立规则」。`
          : tab === 'rules'
            ? `当前已在建立规则。请先点「去课时管理」${hoursNeed}，再回到本页加组件。`
            : `当前在「${here}」。请先跳到课时管理填节数，再跳到建立规则加组件。`
      return {
        path: '/scheduling?tab=hours',
        jumps: [
          { label: tab === 'hours' ? '已在课时管理' : '去课时管理', path: '/scheduling?tab=hours' },
          { label: tab === 'rules' ? '已在建立规则' : '去建立规则', path: '/scheduling?tab=rules' },
        ],
        report: routeLine,
        advice: `建议添加规则组件：学科连堂，目标「${consecutive.subject}」，每周至少 1 天连续 2 节。建立规则里已有模板「${consecutive.subject}连堂规则」。`,
      }
    }
    const slots = extra?.prepSlots
    if (slots?.length) {
      think?.(`判断路由：当前在${placeLabel(extra?.here)}；备课时段是建立规则课位禁排`)
      const ready = await checkPrepPreconditions(slots, think)
      if (!ready.ok) {
        return {
          path: ready.path,
          report: `当前在「${placeLabel(extra?.here)}」。${ready.report}`,
          jumps: [{ label: ready.path.includes('hours') ? '去课时管理' : ready.path.includes('assignments') ? '去任教关系' : ready.path.includes('slots') ? '去课位结构' : '去对应页', path: ready.path }],
        }
      }
      think?.('对照课位禁排模板')
      const lines = slots.map((s) => `${s.subject} ${s.weekday}第${s.periods.join('、')}节`)
      const tab = schedTab(extra?.here)
      return {
        path: '/scheduling?tab=rules',
        jumps: [{ label: tab === 'rules' ? '已在建立规则' : '去建立规则', path: '/scheduling?tab=rules' }],
        report: `当前在「${placeLabel(extra?.here)}」。备课时段不排该科，不是排课时数。学年 ${ready.year} 第${ready.term}学期，${ready.gridLine}。课时和任教已齐，请到建立规则添加。`,
        advice: `建议添加规则组件：课位禁排（按学科、周几、节次）。对照：\n${lines.join('\n')}\n勾选对应模板即可。`,
      }
    }
    think?.(`判断路由：当前在${placeLabel(extra?.here)}`)
    think?.('核对本校课时和任教是否已建')
    const { year, term, gridLine } = await yearGridLine()
    if (!year || year === '未设') {
      return {
        path: '/settings',
        report: `当前在「${placeLabel(extra?.here)}」。还没有当前学年，请先到系统设置。`,
        jumps: [{ label: '去系统设置', path: '/settings' }],
      }
    }
    const resources = await schedulingApi.resources()
    if (!resources.classes.length) {
      return {
        path: '/classes',
        report: `当前在「${placeLabel(extra?.here)}」。还没有行政班，请先建班再配规则。`,
        jumps: [{ label: '去行政班', path: '/classes' }],
      }
    }
    const hourRows = await schedulingApi.courseHours({ academic_year: year, term })
    const hourOk = hourRows.some((h) => (h.weekday_periods || 0) > 0)
    const asgOk = resources.assignments.some((a) => a.academic_year === year && a.term === term && a.teacher_id)
    if (!hourOk || !asgOk) {
      const miss = [!hourOk ? '课时' : '', !asgOk ? '任教' : ''].filter(Boolean).join('和')
      const path = !hourOk ? '/scheduling?tab=hours' : '/scheduling?tab=assignments'
      return {
        path,
        jumps: [{ label: !hourOk ? '去课时管理' : '去任教关系', path }],
        report: `当前在「${placeLabel(extra?.here)}」。规则要先有${miss}，请先跳过去补齐。`,
      }
    }
    const tab = schedTab(extra?.here)
    return {
      path: '/scheduling?tab=rules',
      jumps: [{ label: tab === 'rules' ? '已在建立规则' : '去建立规则', path: '/scheduling?tab=rules' }],
      report: `当前在「${placeLabel(extra?.here)}」。${year} 第${term}学期，${gridLine}。课时和任教已有，请到建立规则按模板添加。`,
      advice: '建议添加规则组件：课位禁排（备课）、学科连堂（数学）、课位必须班主任（周六晚）、班级无空堂、教师日上限。人名要对上档案。',
    }
  }

  if (tool === 'howToUse') {
    const dest = path || '/onboarding'
    return {
      path: dest,
      jumps: [{ label: '去新手引导', path: dest }],
      report: '教务系统建议按这个顺序使用：① 系统设置确认学年学期；② 人员账号、岗位权限和空间资源准备基础数据；③ 建学生、行政班、科目和教师任教；④ 完成学生选课、排课和班级排座；⑤ 配置试卷、考场、日程和监考；⑥ 扫描阅卷并查看成绩。可以打开「新手引导」看当前学校还缺哪一步，也可以在任何页面直接问“这个页面怎么用”或“我下一步做什么”。',
    }
  }

  if (tool === 'howToUseScheduling') {
    const { year, term, gridLine } = await yearGridLine()
    return {
      path: path ?? '',
      report: `这页上面一排 Tab 就是用法。现在学年 ${year} 第${term}学期，${gridLine}。①「课时管理」按班级填每周节数；②「课位结构」确认几天几节、晚自习；③「任教关系」把老师和班对上；④「建立规则」看禁排和教师约束；⑤右侧「生成课表」由你点，冲突格会标红。想排某一级可以说「我想排高一的课」，我会帮你切到该年级课时。`,
    }
  }

  if (tool === 'guideGrade') {
    const label = extra?.grade || '高一'
    const { year, term, gridLine } = await yearGridLine()
    const grades = await orgApi.grades()
    const grade = grades.find((g) => g.name.includes(label) || (label === '高一' && g.level === 1) || (label === '高二' && g.level === 2) || (label === '高三' && g.level === 3))
    if (!grade) {
      return {
        path: '/classes',
        report: `还没有找到「${label}」。请先在行政班/年级里建好 ${label}，再回来说「我想排${label}的课」。当前学年 ${year} 第${term}学期。`,
      }
    }
    const resources = await schedulingApi.resources()
    const classes = resources.classes.filter((c) => Number(c.grade_id) === grade.id)
    const names = classes.slice(0, 6).map((c) => c.name).join('、')
    return {
      path: `/scheduling?tab=hours&grade=${grade.id}`,
      report: `按${label}来排。已打开课时管理。学年 ${year} 第${term}学期，${gridLine}。${label}现有 ${classes.length} 个班${names ? `（${names}${classes.length > 6 ? '…' : ''}）` : ''}。接下来：把该年级各班课时填齐 → 任教关系对上老师 → 课位结构确认 → 建立规则过一遍 → 你点生成。`,
    }
  }

  if (tool === 'go') {
    const dest = path || '/'
    const byPath: Record<string, string> = {
      '/students': '已打开学生档案。名单在这里导入。排课前还要有年级和行政班。',
      '/file-center': '已打开文件中心。课表导出是后台任务，完成后在这里取文件。',
      '/seating': '已打开班级排座。这和排课生成的日课表不是同一件事。',
      '/subjects': '已打开科目管理。课时里没有的科目要先在这里建。',
      '/classes': '已打开行政班。没有年级班级无法排课。',
    }
    return { path: dest, report: byPath[dest] || '已打开。' }
  }

  if (tool === 'openScheduling') {
    const { year, term, gridLine } = await yearGridLine()
    const dest = path || '/scheduling?tab=rules'
    const tab = dest.includes('tab=') ? dest.split('tab=')[1]?.split('&')[0] : 'rules'
    const byTab: Record<string, string> = {
      hours: `已打开课时管理。学年 ${year} 第${term}学期，${gridLine}。按班填每周节数。说「每周36节怎么安排」可以先看预览，写入还要你确认。`,
      slots: `已打开课位结构。学年 ${year} 第${term}学期，${gridLine}。几天几节、晚自习在这里保存。`,
      assignments: `已打开任教关系。学年 ${year} 第${term}学期。缺任教先补，或按课时方案自动生成（先校验再写入）。`,
      rules: `已打开建立规则。学年 ${year} 第${term}学期，${gridLine}。禁排、固定课、连堂、教师约束在这里。`,
      schedule: `已打开课表。学年 ${year} 第${term}学期。冲突格会标红。`,
    }
    return {
      path: dest,
      report: byTab[tab] || `已打开排课。当前学年 ${year}，第 ${term} 学期。${gridLine}。`,
    }
  }

  if (tool === 'countSubjectTeachers') {
    think?.('分析意图：查该科任教人数')
    think?.('查询本校教师档案')
    const want = extra?.subject || '语文'
    const meta = await teacherProfilesApi.filters()
    const year = meta.defaults?.academic_year || null
    const term = meta.defaults?.term || '1'
    const subject = (meta.subjects || []).find((s) => s.name === want || s.name.includes(want))
    if (!subject) {
      return {
        path: '/teacher-profiles',
        report: `科目库里没有「${want}」。请先在科目管理里建好，或换一个本校正在用的科目名。`,
      }
    }
    const list = await teacherProfilesApi.list({
      academic_year: year,
      term,
      subject_id: subject.subject_id,
    })
    const names = list.items.slice(0, 8).map((t) => t.name).join('、')
    const extraNames = list.total > 8 ? '…' : ''
    return {
      path: '/teacher-profiles',
      report: `${year || '当前学年'}第${term}学期，任教「${subject.name}」的在职教师 ${list.total} 人${names ? `：${names}${extraNames}` : '。档案里还没有任教关系'}。这是本校现网数据，按任教科目统计，停用账号不计入。`,
    }
  }

  if (tool === 'checkTeachers') {
    const meta = await teacherProfilesApi.filters()
    const year = meta.defaults?.academic_year || null
    const term = meta.defaults?.term || '1'
    const list = await teacherProfilesApi.list({
      academic_year: year,
      term,
    })
    const ratio = list.class_summary ? Math.round(list.class_summary.completion_ratio) : 0
    const target = list.class_summary?.weekly_target ?? 0
    const scheduled = list.class_summary?.scheduled_lessons ?? 0
    return {
      path: '/teacher-profiles',
      report: `${year || '当前学年'} · 第${term}学期，完成度 ${ratio}%（已排 ${scheduled} / 目标 ${target}）。按课时网格核算，停用教师不进列表。`,
    }
  }

  const { year, term, gridLine } = await yearGridLine()
  return {
    path: '/settings',
    report: `已打开系统设置。学年 ${year}，学期 ${term}。${gridLine}。我不会替你保存或滚动学年。`,
  }
}
