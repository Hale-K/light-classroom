import { routeTitle } from '../router/meta.ts'

const SCHED_TABS: Record<string, string> = {
  hours: '排课 · 课时管理',
  slots: '排课 · 课位结构',
  rules: '排课 · 建立规则',
  assignments: '排课 · 任教关系',
  schedule: '排课 · 课表',
}

export function hereOf(pathname: string, search = ''): string {
  return `${pathname}${search || ''}`
}

export function placeLabel(here?: string): string {
  if (!here) return '当前页'
  const q = here.indexOf('?')
  const path = q >= 0 ? here.slice(0, q) : here
  const tab = new URLSearchParams(q >= 0 ? here.slice(q + 1) : '').get('tab') || ''
  if (path.startsWith('/scheduling')) return SCHED_TABS[tab] || '排课管理'
  if (path.startsWith('/campus-buildings') || path.startsWith('/campus')) {
    if (tab === 'allocation') return '空间资源 · 分配规则'
    if (tab === 'class-planning') return '空间资源 · 班级划分'
    return '空间资源'
  }
  return routeTitle(path)
}

export function schedTab(here?: string): string {
  if (!here || !here.startsWith('/scheduling')) return ''
  const q = here.indexOf('?')
  return new URLSearchParams(q >= 0 ? here.slice(q + 1) : '').get('tab') || ''
}

export function samePlace(here: string, dest: string): boolean {
  const strip = (s: string) => s.replace(/\/$/, '')
  const a = strip(here)
  const b = strip(dest)
  if (a === b) return true
  const ap = a.split('?')[0]
  const bp = b.split('?')[0]
  if (ap !== bp) return false
  const at = new URLSearchParams(a.split('?')[1] || '').get('tab') || ''
  const bt = new URLSearchParams(b.split('?')[1] || '').get('tab') || ''
  if (ap.startsWith('/scheduling')) return at === bt
  return at === bt || (!at && !bt)
}

export function jumpLabel(dest: string): string {
  return `跳转到「${placeLabel(dest)}」`
}
