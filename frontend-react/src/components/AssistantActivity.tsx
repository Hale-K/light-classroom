import Icon from './Icon'
import type { AssistantRun } from '@/api'
import { activityLines } from '@/assistant/activity'
import AssistantExecutionBadge from './AssistantExecutionBadge'

export default function AssistantActivity({ live, progress, connection, saved = [] }: {
  live?: string; progress?: AssistantRun | null; connection?: string;
  saved?: ReturnType<typeof activityLines>;
}) {
  const lines = progress ? activityLines(progress.events ?? []) : saved
  const waiting = Boolean(live)
  const seconds = progress?.elapsed_seconds ?? 0
  return (
    <div className="assist-activity" aria-label="助手执行进展">
      {waiting && <p className="assist-activity-intro">已收到。我会先理解你的要求，需要时查询相关数据，再给出答复。</p>}
      {waiting && <AssistantExecutionBadge execution={progress?.execution} live />}
      {lines.length > 0 && <ol className="assist-activity-lines">
        {lines.map((line, i) => <li key={i} className={`is-${line.kind}`}>
          {line.kind === 'tool' ? <Icon name="file-text" size={15} /> : null}
          <span>{line.text}</span>
        </li>)}
      </ol>}
      {waiting && <div className="assist-activity-status" role="status" aria-live="polite">
        <i aria-hidden="true" /><span>{live}{seconds > 0 ? ` · ${seconds} 秒` : ''}</span>
      </div>}
      {waiting && progress && progress.phase_elapsed_seconds >= 15 && <p className="assist-activity-wait">这一阶段耗时较长，尚未收到新结果。你可以补充要求或停止。</p>}
      {waiting && connection && connection !== '实时连接中' && <p className="assist-activity-wait">{connection}</p>}
    </div>
  )
}
