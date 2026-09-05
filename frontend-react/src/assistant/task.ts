import { assistantApi, type AssistantRun } from '@/api'
import { ApiError } from '@/api/http'

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
      if (failures >= 4) throw new Error('暂时无法连接后台。已保留任务编号，可以点“恢复查看”继续核对结果。')
      await pause(2000, signal)
      continue
    }
    onUpdate(run)
    if (run.status !== 'running') return run
    if (Date.now() - started > 150000) throw new Error('仍未收到结束状态。可以稍后恢复查看，不需要重复发送需求。')
    await pause(1500, signal)
  }
  throw new DOMException('已停止查看', 'AbortError')
}
