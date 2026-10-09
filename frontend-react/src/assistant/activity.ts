import type { AssistantExecution } from '@/api'

type ActivityEvent = { phase: string; message: string; visibility?: string }

/** Public execution milestones only. Never use model traces or query payloads. */
export function activityLines(events: ActivityEvent[]) {
  const lines: { kind: 'tool' | 'update'; text: string }[] = []
  for (const event of events) {
    if (event.visibility === 'internal') continue
    if (!['tool', 'observed', 'recovering', 'isolated', 'planning', 'checking'].includes(event.phase)) continue
    const text = event.message.trim()
    if (!text || lines.at(-1)?.text === text) continue
    lines.push({ kind: event.phase === 'tool' ? 'tool' : 'update', text })
  }
  return lines.slice(-12)
}

export function restoreActivity(value: unknown): ReturnType<typeof activityLines> {
  if (!Array.isArray(value)) return []
  return value.slice(-12).flatMap(item => {
    if (!item || !['tool', 'update'].includes(item.kind) || typeof item.text !== 'string') return []
    return [{ kind: item.kind as 'tool' | 'update', text: item.text.slice(0, 300) }]
  })
}

export function executionModeLabel(mode: string) {
  return mode === 'planning' ? '复杂规划/执行' : mode === 'query' ? '普通问答/查询' : ''
}

export function executionStatusLabel(status: AssistantExecution['tasks'][number]['status']) {
  return ({ pending: '待执行', running: '进行中', succeeded: '完成', completed: '完成', failed: '失败', blocked: '待补充',
    skipped: '已跳过', cancelled: '已取消', timed_out: '超时' })[status]
}

/** Restore public progress only, including older conversation mode names. */
export function restoreExecution(raw: unknown): AssistantExecution | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const mode = value.mode === 'supervisor' ? 'planning'
    : value.mode === 'direct' || value.mode === 'agent' ? 'query' : value.mode
  if (mode !== 'query' && mode !== 'planning' && mode !== 'pending') return undefined
  const tasks: AssistantExecution['tasks'] = Array.isArray(value.tasks) ? value.tasks.slice(0, 20).flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const task = item as Record<string, unknown>
    const status = task.status === 'completed' ? 'succeeded' : task.status
    if (typeof task.id !== 'string' || typeof task.label !== 'string'
      || !['pending', 'running', 'succeeded', 'failed', 'blocked', 'skipped', 'cancelled', 'timed_out'].includes(String(status))) return []
    return [{
      id: task.id.slice(0, 80), label: task.label.slice(0, 100),
      status: status as AssistantExecution['tasks'][number]['status'],
      summary: typeof task.summary === 'string' ? task.summary.slice(0, 500) : undefined,
      attempt: typeof task.attempt === 'number' ? task.attempt : undefined,
      retry_count: typeof task.retry_count === 'number' ? task.retry_count : undefined,
    }]
  }) : []
  return { mode, tasks, multi_agent: value.multi_agent === true,
    kind: value.kind === 'readiness' || value.kind === 'diagnosis' ? value.kind : null,
    goal: typeof value.goal === 'string' ? value.goal.slice(0, 300) : undefined }
}
