import { clarify } from '@/assistant/clarify'
import { isHoursPlan, parseWeeklyTotal } from '@/assistant/hoursPlan'
import { type ConsecutiveHint, type PrepSlot } from '@/assistant/intent'
import { isHowToUse, isSchedulingPageHelp, matchPlaybook } from '@/assistant/playbook'
import { type RuleGuide } from '@/assistant/ruleGuide'
import {
  isCountSubjectTeachers,
  isGradeSchedule,
  parseGradeLabel,
  parseSubjectLabel,
  type AssistantTool,
} from '@/assistant/run'
import { CORE_TASKS } from '@/assistant/skills'

export type Extra = {
  grade?: string
  subject?: string
  weekly?: number
  prepSlots?: PrepSlot[]
  consecutive?: ConsecutiveHint
  ruleGuide?: RuleGuide
  here?: string
  traceId?: string
}

export type Route =
  | { kind: 'tool'; tool: AssistantTool; path: string; extra?: Extra }
  | { kind: 'say'; text: string }
  | { kind: 'llm' }

/** 教务编排：先工具，再说明书口径，再模型。不上 LangGraph。 */
export function routeTeacherMessage(text: string, pathname: string): Route {
  const content = text.trim()
  if (!content) return { kind: 'say', text: '请说一句排课相关的话。' }

  if (isSchedulingPageHelp(content)) {
    const onPage = pathname.startsWith('/scheduling')
    return { kind: 'tool', tool: 'howToUseScheduling', path: onPage ? '' : '/scheduling?tab=hours' }
  }
  if (isHowToUse(content)) {
    return { kind: 'tool', tool: 'howToUse', path: '/scheduling?tab=hours' }
  }
  // 规则和本校现状交给后端工具循环，保留完整上下文与确认草稿。
  if (/规则|禁排|不能排|不排|连堂|连着上|备课|每天最多|每日上限|班主任|准备|还缺什么/.test(content)) {
    return { kind: 'llm' }
  }
  if (isHoursPlan(content)) {
    return {
      kind: 'tool',
      tool: 'proposeHours',
      path: '/scheduling?tab=hours',
      extra: { grade: parseGradeLabel(content) || '高一', weekly: parseWeeklyTotal(content) ?? undefined },
    }
  }
  const grade = parseGradeLabel(content)
  if (grade && isGradeSchedule(content)) {
    return { kind: 'tool', tool: 'guideGrade', path: '/scheduling?tab=hours', extra: { grade } }
  }
  if (isCountSubjectTeachers(content)) {
    return {
      kind: 'tool',
      tool: 'countSubjectTeachers',
      path: '/teacher-profiles',
      extra: { subject: parseSubjectLabel(content) || '语文' },
    }
  }
  if (/打开排课|核对规则后再生成/.test(content)) {
    return { kind: 'tool', tool: CORE_TASKS[0].tool, path: CORE_TASKS[0].path }
  }
  if (/教师档案|课时算满/.test(content)) {
    return { kind: 'tool', tool: CORE_TASKS[1].tool, path: CORE_TASKS[1].path }
  }
  if (/学年学期|系统设置核对/.test(content)) {
    return { kind: 'tool', tool: CORE_TASKS[2].tool, path: CORE_TASKS[2].path }
  }
  if (/打开规则组/.test(content) && !/哪个组件|不能排|禁排/.test(content)) {
    return { kind: 'tool', tool: 'openScheduling', path: '/scheduling?tab=rules' }
  }
  if (/规则组|禁排|不能排|哪个组件|固定课|空堂|多班教师|班主任/.test(content)) {
    return { kind: 'llm' }
  }
  if (/课位结构|几天几节|保存网格/.test(content)) {
    return { kind: 'tool', tool: 'openScheduling', path: '/scheduling?tab=slots' }
  }
  if (/任教关系|缺任教|对老师/.test(content) && !isCountSubjectTeachers(content)) {
    return { kind: 'tool', tool: 'openScheduling', path: '/scheduling?tab=assignments' }
  }
  if (/课时管理|填课时/.test(content) && !isHoursPlan(content)) {
    return { kind: 'tool', tool: 'openScheduling', path: '/scheduling?tab=hours' }
  }
  if (/打开课表|看课表|课表在哪/.test(content) && !/空了/.test(content)) {
    return { kind: 'tool', tool: 'openScheduling', path: '/scheduling?tab=schedule' }
  }
  if (/导入学生|学生名单/.test(content)) {
    return { kind: 'tool', tool: 'go', path: '/students' }
  }
  if (/导出课表|课表文件/.test(content)) {
    return { kind: 'tool', tool: 'go', path: '/file-center' }
  }
  if (/排座|座位/.test(content) && !/课位/.test(content)) {
    return { kind: 'tool', tool: 'go', path: '/seating' }
  }
  if (/科目管理|没有这(个)?科/.test(content)) {
    return { kind: 'tool', tool: 'go', path: '/subjects' }
  }
  if (/行政班|没有班/.test(content)) {
    return { kind: 'tool', tool: 'go', path: '/classes' }
  }
  const unclear = clarify(content)
  if (unclear) return { kind: 'say', text: unclear.text }
  const canned = matchPlaybook(content)
  if (canned) return { kind: 'say', text: canned }
  return { kind: 'llm' }
}
