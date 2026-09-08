import { assistantApi, type AssistantRun } from '@/api'
import { ApiError } from '@/api/http'

const MAX_READ_FAILURES = 12
const MAX_WATCH_MS = 300000

function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const stop = () => { clearTimeout(timer); reject(new DOMException('已停止查看', 'AbortError')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve() }, ms)
    if (signal.aborted) stop()
    else signal.addEventListener('abort', stop, { once: true })
  })
}

/** 只轮询同一个任务。断网不重新调用模型，终态后停止轮询。 */
export async function watchAssistantRun(id: string, signal: AbortSignal, onUpdate: (run: AssistantRun) => void, onConnection: (message: string) => void): Promise<AssistantRun> {
  let failures = 0
  const started = Date.now()
  while (!signal.aborted) {
    let run: AssistantRun
    try {
      run = await assistantApi.readRun(id, signal)
      failures = 0
      onConnection('')
    } catch (error) {
      if (signal.aborted) throw error
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) throw error
      failures++
      onConnection(`暂时无法连接后台，正在重连（第 ${failures} 次）。任务可能仍在处理，不会重复提交。`)
      if (failures >= MAX_READ_FAILURES) throw new Error('后台暂时无法连接。任务仍未重新提交，已保留任务编号，请稍后点击“恢复查看”。')
      await pause(Math.min(2000 + failures * 1000, 10000), signal)
      continue
    }
    onUpdate(run)
    if (run.status !== 'running') return run
    if (Date.now() - started > MAX_WATCH_MS) throw new Error('任务仍在后台运行，暂未收到结束状态。可以稍后恢复查看，不需要重复发送需求。')
    await pause(1500, signal)
  }
  throw new DOMException('已停止查看', 'AbortError')
}
