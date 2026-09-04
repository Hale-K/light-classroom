import { routeTitle } from '@/router/meta'
import type { AssistantTool } from './run'

export type AssistantTask = { label: string; path: string; tool: AssistantTool }

export type PageSkill = {
  id: string
  match: string
  can: string[]
  cannot: string[]
  tasks: AssistantTask[]
}

export const CORE_TASKS: AssistantTask[] = [
  { label: '帮我打开排课工作台，核对规则后再生成', path: '/scheduling?tab=rules', tool: 'openScheduling' },
  { label: '帮我看教师档案完成度是否按课时算满', path: '/teacher-profiles', tool: 'checkTeachers' },
  { label: '帮我去系统设置核对学年学期和网格', path: '/settings', tool: 'checkSettings' },
]

const SKILLS: PageSkill[] = [
  {
    id: 'scheduling',
    match: '/scheduling',
    can: ['打开排课并切到规则组', '读取学年学期和网格', '说明冲突格会标红'],
    cannot: ['不会替你点生成或改格子', '不会改 COS / 云主机'],
    tasks: [
      { label: '当前就在排课：先看课时与规则组，冲突格会标红', path: '/scheduling?tab=hours', tool: 'openScheduling' },
      CORE_TASKS[1],
      CORE_TASKS[2],
    ],
  },
  {
    id: 'teacher-profiles',
    match: '/teacher-profiles',
    can: ['打开教师档案并读取完成度'],
    cannot: ['不会改任教或停用教师'],
    tasks: CORE_TASKS,
  },
  {
    id: 'settings',
    match: '/settings',
    can: ['打开系统设置并核对学年学期、网格'],
    cannot: ['不会替你保存设置'],
    tasks: CORE_TASKS,
  },
  {
    id: 'ai-providers',
    match: '/ai-providers',
    can: ['留在本页说明服务商字段', '跳到排课 / 档案 / 设置'],
    cannot: ['不会代填 API Key', '不会操作腾讯云控制台'],
    tasks: CORE_TASKS,
  },
]

const FALLBACK: PageSkill = {
  id: 'default',
  match: '/',
  can: ['打开排课 / 档案 / 设置并核对现网数据'],
  cannot: ['不会代操作云产品', '不会替你点生成或保存设置'],
  tasks: CORE_TASKS,
}

export function skillFor(pathname: string): PageSkill {
  const hit = SKILLS.filter((s) => pathname === s.match || pathname.startsWith(`${s.match}/`)).sort(
    (a, b) => b.match.length - a.match.length,
  )[0]
  return hit ?? FALLBACK
}

export function pageSnapshot(pathname: string) {
  const skill = skillFor(pathname)
  return {
    path: pathname,
    title: routeTitle(pathname),
    can: skill.can,
    cannot: skill.cannot,
    tasks: skill.tasks,
  }
}
