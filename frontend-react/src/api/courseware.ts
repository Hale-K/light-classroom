/** 课件管理领域 API（上传 / AI 生成互动课件 / 链接收藏）。 */
import type { CourseCatalog, CoursewareInfo, GeneratedImageInfo } from '@/types'
import { http, unwrap } from './http'

export interface CoursewareQuery {
  stage?: string
  grade?: string
  subject?: string
  keyword?: string
  courseware_type?: string
}

export interface CoursewareLinkPayload {
  title: string
  source_url: string
  stage?: string
  grade_name?: string
  subject_name?: string
  textbook_version?: string
  chapter?: string
  remark?: string
}

export interface CoursewareGeneratePayload {
  title: string
  stage: string
  grade_name: string
  subject_name: string
  textbook_version?: string
  chapter?: string
  requirement?: string
}

/**
 * SSE 流式生成课件：model（当前服务商）→ progress（已接收字符数）→ done（课件入库）。
 * 走原生 fetch 读流（axios 不支持浏览器侧流式读取）。
 */
export async function generateCoursewareStream(
  payload: CoursewareGeneratePayload,
  handlers: { onProgress?: (chars: number) => void; onModel?: (name: string) => void } = {},
  signal?: AbortSignal,
): Promise<CoursewareInfo> {
  const { getAuthHeaders, getSseApiBaseURL } = await import('./http')
  const resp = await fetch(`${getSseApiBaseURL()}/courseware/generate/stream`, {
    method: 'POST',
    headers: {
      ...getAuthHeaders(),
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
    signal,
  })
  if (!resp.ok || !resp.body) {
    let detail = `生成连接失败（${resp.status}）`
    try {
      const body = (await resp.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch { /* 非 JSON 响应体，保留默认提示 */ }
    throw new Error(detail)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let result: CoursewareInfo | null = null
  let errorMessage = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      const raw = line.slice(5).trim()
      if (!raw) continue
      try {
        const payload = JSON.parse(raw) as { type?: string; chars?: number; message?: string; item?: CoursewareInfo; name?: string; model?: string }
        if (payload.type === 'progress' && typeof payload.chars === 'number') handlers.onProgress?.(payload.chars)
        else if (payload.type === 'start' && payload.model) handlers.onModel?.(payload.model)
        else if (payload.type === 'model' && payload.name) handlers.onModel?.(payload.name)
        else if (payload.type === 'done' && payload.item) result = payload.item
        else if (payload.type === 'error' && payload.message) errorMessage = payload.message
      } catch { /* 忽略无法解析的行 */ }
    }
  }
  if (errorMessage) throw new Error(errorMessage)
  if (!result) throw new Error('生成连接中断，请重试')
  return result
}

export const coursewareApi = {
  catalog: () => unwrap<CourseCatalog>(http.get('/courseware/catalog')),
  list: (params?: CoursewareQuery) => unwrap<CoursewareInfo[]>(http.get('/courseware', { params })),
  detail: (id: number) => unwrap<CoursewareInfo>(http.get(`/courseware/${id}`)),
  upload: (form: FormData) => unwrap<CoursewareInfo>(http.post('/courseware/upload', form, { timeout: 300000 })),
  createLink: (data: CoursewareLinkPayload) => unwrap<CoursewareInfo>(http.post('/courseware', data)),
  update: (id: number, data: Partial<CoursewareLinkPayload>) =>
    unwrap<CoursewareInfo>(http.patch(`/courseware/${id}`, data)),
  remove: (id: number) => unwrap<{ id: number }>(http.delete(`/courseware/${id}`)),
  download: (id: number) =>
    unwrap<{ url: string; file_name: string; file_size: number }>(http.get(`/courseware/${id}/download`)),
  generateImages: (data: { prompt: string; size?: string }) =>
    unwrap<{ items: GeneratedImageInfo[] }>(http.post('/courseware/images/generate', data, { timeout: 180000 })),
}
