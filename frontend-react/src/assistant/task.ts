import { assistantApi, type AssistantRun } from '@/api'
import { ApiError } from '@/api/http'
import { getAuthHeaders, getSseApiBaseURL } from '@/api/http'

const MAX_READ_FAILURES = 12
const MAX_WATCH_MS = 300000
const SSE_IDLE_MS = 8000

function isActiveRun(status: AssistantRun['status']) {
  return status === 'queued' || status === 'running'
}

function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const stop = () => { clearTimeout(timer); reject(new DOMException('已停止查看', 'AbortError')) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', stop); resolve() }, ms)
    if (signal.aborted) stop()
    else signal.addEventListener('abort', stop, { once: true })
  })
}

async function readSseChunk(reader: ReadableStreamDefaultReader<Uint8Array>) {
  let timer = 0
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        timer = window.setTimeout(() => reject(new Error('SSE idle timeout')), SSE_IDLE_MS)
      }),
    ])
  } finally {
    window.clearTimeout(timer)
  }
}

/** 只轮询同一个任务。断网不重新调用模型，终态后停止轮询。 */
export async function watchAssistantRun(id: string, signal: AbortSignal, onUpdate: (run: AssistantRun) => void, onConnection: (message: string) => void): Promise<AssistantRun> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  try {
    const response = await fetch(`${getSseApiBaseURL()}/assistant/runs/${encodeURIComponent(id)}/stream`, {
      headers: { ...getAuthHeaders(), Accept: 'text/event-stream' }, signal,
      credentials: 'include',
      cache: 'no-store',
    })
    if (!response.ok || !response.body) throw new Error('SSE unavailable')
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let latest: AssistantRun | undefined
    while (!signal.aborted) {
      const { value, done } = await readSseChunk(reader)
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) {
        const data = frame.split('\n').find((line) => line.startsWith('data: '))?.slice(6)
        if (!data) continue
        try {
          const payload = JSON.parse(data)
          if (frame.includes('event: run.status')) {
            latest = { ...(latest || {} as AssistantRun), ...payload } as AssistantRun
            onUpdate(latest)
            onConnection('实时连接中')
            if (!isActiveRun(payload.status)) return latest
          }
        } catch { /* ignore malformed frame; polling fallback remains available */ }
      }
    }
    if (latest && !isActiveRun(latest.status)) return latest
  } catch (error) {
    if (signal.aborted) throw error
    await reader?.cancel().catch(() => undefined)
    onConnection('实时连接不可用，正在切换为轮询查看')
  }
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
    if (!isActiveRun(run.status)) return run
    if (Date.now() - started > MAX_WATCH_MS) throw new Error('任务仍在后台运行，暂未收到结束状态。可以稍后恢复查看，不需要重复发送需求。')
    await pause(1500, signal)
  }
  throw new DOMException('已停止查看', 'AbortError')
}
