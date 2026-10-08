/** ai 领域 API（由 api/index.ts 拆分）。 */
import { http, unwrap } from './http'
import type { AssistantMaterial } from '@/assistant/materials'

export type AiProvider = {
  id: number
  name: string
  provider_type: string
  base_url: string
  has_api_key: boolean
  chat_model?: string | null
  vision_model?: string | null
  image_model?: string | null
  video_model?: string | null
  audio_model?: string | null
  timeout_seconds: number
  is_default: boolean
  status: number
  sort: number
  remark?: string | null
  last_test_status?: number | null
  last_test_at?: string | null
}

export type AiProviderForm = {
  name: string
  provider_type: string
  base_url: string
  api_key?: string
  chat_model?: string | null
  vision_model?: string | null
  image_model?: string | null
  video_model?: string | null
  audio_model?: string | null
  timeout_seconds?: number
  is_default?: boolean
  status?: number
  sort?: number
  remark?: string | null
}

export const aiProviderApi = {
  list: (params?: { keyword?: string; status?: number }) =>
    unwrap<AiProvider[]>(http.get('/ai-providers', { params })),
  create: (data: AiProviderForm) => unwrap<AiProvider>(http.post('/ai-providers', data)),
  update: (id: number, data: AiProviderForm) => unwrap<boolean>(http.put(`/ai-providers/${id}`, data)),
  updateStatus: (id: number, status: number) =>
    unwrap<boolean>(http.put(`/ai-providers/${id}/status`, null, { params: { status } })),
  setDefault: (id: number) => unwrap<boolean>(http.put(`/ai-providers/${id}/default`)),
  remove: (id: number) => unwrap<boolean>(http.delete(`/ai-providers/${id}`)),
  test: (id: number) => unwrap<boolean>(http.post(`/ai-providers/${id}/test`)),
  loadModels: (data: { provider_type?: string; base_url: string; api_key?: string }) =>
    unwrap<string[]>(http.post('/ai-providers/load-models', data)),
}

export type AssistantPlan = {
  id: string
  status: 'pending' | 'executed' | 'cancelled'
  summary: string
  expires_at: string
  result?: { text: string; path: string; count: number } | null
}

export type AssistantExecution = {
  mode: 'pending' | 'direct' | 'agent' | 'supervisor'
  multi_agent: boolean
  kind: 'readiness' | 'diagnosis' | null
  tasks: {
    id: string
    label: string
    status: 'running' | 'succeeded' | 'failed'
    attempt?: number
    retry_count?: number
    allowed_tools?: string[]
  }[]
}

export type AssistantRun = {
  id: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted'
  phase: string
  message: string
  elapsed_seconds: number
  phase_elapsed_seconds: number
  heartbeat_at: string
  events: { phase: string; message: string; at: string }[]
  execution?: AssistantExecution
  result?: { text: string; think?: string[]; choices?: { label: string; send: string }[]; plan?: AssistantPlan | null; jumps?: { label: string; path: string; requires_confirmation?: boolean }[]; model_visible?: boolean } | null
}

export type AssistantConversation = {
  messages: { role: 'user' | 'assistant'; content: string; model_visible?: boolean }[]
  summary: string
  updated_at?: string | null
}

export const assistantApi = {
  readAttachment: (file: File, signal?: AbortSignal) => {
    const data = new FormData()
    data.append('file', file)
    return unwrap<AssistantMaterial>(http.post('/assistant/attachments/read', data, { timeout: 30000, signal }))
  },
  conversation: () => unwrap<AssistantConversation>(http.get('/assistant/conversation', { timeout: 5000 })),
  saveConversation: (messages: AssistantConversation['messages']) =>
    unwrap<AssistantConversation>(http.put('/assistant/conversation', { messages }, { timeout: 5000 })),
  clearConversation: () => unwrap<{ cleared: boolean }>(http.delete('/assistant/conversation', { timeout: 5000 })),
  startRun: (data: Record<string, unknown>, signal?: AbortSignal) =>
    unwrap<AssistantRun>(http.post('/assistant/runs', data, { timeout: 8000, signal })),
  readRun: (id: string, signal?: AbortSignal) =>
    unwrap<AssistantRun>(http.get(`/assistant/runs/${encodeURIComponent(id)}`, { timeout: 5000, signal })),
  steerRun: (id: string, content: string) =>
    unwrap<{ accepted: boolean; kind: 'steer'; message_id: string }>(
      http.post(`/assistant/runs/${encodeURIComponent(id)}/steer`, { content }, { timeout: 5000 }),
    ),
  cancelRun: (id: string) =>
    unwrap<AssistantRun>(http.post(`/assistant/runs/${encodeURIComponent(id)}/cancel`, {}, { timeout: 5000 })),
  decide: (id: string, decision: 'confirm' | 'cancel') =>
    unwrap<AssistantPlan>(http.post(`/assistant/actions/${encodeURIComponent(id)}`, { decision })),
}

export type KnowledgeBase = {
  id: number
  name: string
  description: string
  embedding_model: string
  enabled: boolean
  created_at?: string | null
}

export const knowledgeApi = {
  list: () => unwrap<KnowledgeBase[]>(http.get('/knowledge')),
  create: (data: Pick<KnowledgeBase, 'name' | 'description' | 'embedding_model'>) =>
    unwrap<KnowledgeBase>(http.post('/knowledge', data)),
  setStatus: (id: number, enabled: boolean) =>
    unwrap<KnowledgeBase>(http.patch(`/knowledge/${id}/status`, null, { params: { enabled } })),
  remove: (id: number) => unwrap<{ deleted: boolean }>(http.delete(`/knowledge/${id}`)),
}

