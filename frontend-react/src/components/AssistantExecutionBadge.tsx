import type { AssistantExecution } from '@/api'
import { executionModeLabel, executionStatusLabel } from '@/assistant/activity'

export default function AssistantExecutionBadge({ execution, live = false }: {
  execution?: AssistantExecution; live?: boolean;
}) {
  if (!execution) return null
  const label = executionModeLabel(execution.mode)
  if (!label) return null
  if (!execution.tasks.length) return <p className="assist-execution" aria-label="助手执行模式">{label}</p>
  const completed = execution.tasks.filter(task => task.status === 'succeeded' || task.status === 'completed').length
  const failed = execution.tasks.some(task => ['failed', 'timed_out', 'blocked'].includes(task.status))
  return <details className="assist-execution" aria-label="助手任务计划" open={live || undefined}>
    <summary>{label} · {completed}/{execution.tasks.length} 项完成{failed ? ' · 有未完成项' : ''}</summary>
    {execution.goal && <p className="assist-execution-goal">{execution.goal}</p>}
    <ul aria-label="计划步骤状态">
      {execution.tasks.map(task => <li key={task.id}>
        <span>{task.label} · {executionStatusLabel(task.status)}</span>
        {task.summary && <small className="assist-execution-result">{task.summary}</small>}
      </li>)}
    </ul>
  </details>
}
