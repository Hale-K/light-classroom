/**
 * HTTP 客户端封装：统一携带 JWT + X-School-Code，统一解包/错误/401 处理。
 * 响应按后端规范 `{ code, message, data }` 解包，成功直接返回 data。
 */
import axios, { AxiosResponse, type AxiosInstance } from 'axios'
import { DEFAULT_SCHOOL_CODE } from '@/types'
import type { ApiResponse } from '@/types'

export class ApiError extends Error {
  code: number
  status: number
  traceId?: string
  constructor(message: string, code = -1, status = 0, traceId?: string) {
    super(message)
    this.code = code
    this.status = status
    this.traceId = traceId
  }
}

/** 运行时读取 token / school_code，避免循环依赖与 import 时序问题 */
export interface AuthResolver {
  getToken: () => string | null
  getAdminToken: () => string | null
  getSchoolCode: () => string
  onUnauthorized: () => void
  onForbidden?: () => void
}
function readSchoolCode(): string {
  const c = (localStorage.getItem('zh_school_code') || '').trim()
  // 归一化历史残留值（早期默认 'default' 与后端租户 'demo' 不一致）
  return !c || c === 'default' ? DEFAULT_SCHOOL_CODE : c
}

let resolver: AuthResolver = {
  getToken: () => localStorage.getItem('zh_token'),
  getAdminToken: () => localStorage.getItem('zh_admin_token'),
  getSchoolCode: readSchoolCode,
  onUnauthorized: () => {
    localStorage.removeItem('zh_token')
    localStorage.removeItem('zh_user')
    window.location.href = '/login'
  },
  onForbidden: undefined,
}
export function setAuthResolver(r: AuthResolver) {
  resolver = { ...resolver, ...r }
}

/** FastAPI 422 的 detail 是对象数组（{loc, msg, type}），拼成可读文案，避免页面出现 [object Object] */
function normalizeErrorDetail(detail: unknown): string | undefined {
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        const item = (d ?? {}) as { loc?: unknown; msg?: unknown }
        const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
        const msg = typeof item.msg === 'string' ? item.msg : ''
        return [loc, msg].filter(Boolean).join(': ')
      })
      .filter(Boolean)
    if (parts.length === 0) return undefined
    const head = parts.length > 1 ? `${parts[0]}（等 ${parts.length} 条校验错误）` : parts[0]
    return `参数校验失败：${head}`
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  if (typeof detail === 'string' && detail) return detail
  return undefined
}

/** 判断是否为平台超管接口（/api/v1/admin/...） */
function isAdminUrl(url?: string): boolean {
  return !!url && url.startsWith('/admin')
}

function newTraceId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replace(/-/g, '').slice(0, 16)
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 10)}`.slice(0, 16)
}

function readTraceId(headers?: AxiosResponse['headers'], body?: unknown): string | undefined {
  const fromHeader = headers?.['x-trace-id'] || headers?.['X-Trace-Id']
  if (typeof fromHeader === 'string' && fromHeader) return fromHeader
  if (body && typeof body === 'object' && 'trace_id' in body) {
    const value = (body as { trace_id?: unknown }).trace_id
    if (typeof value === 'string' && value) return value
  }
  return undefined
}

function createHttp(baseURL: string): AxiosInstance {
  const http = axios.create({
    baseURL,
    timeout: 20000,
    withCredentials: false,
  })

  http.interceptors.request.use((config) => {
    const token = isAdminUrl(config.url) ? resolver.getAdminToken() : resolver.getToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
    config.headers['X-School-Code'] = resolver.getSchoolCode()
    config.headers['X-Trace-Id'] = newTraceId()
    return config
  })

  http.interceptors.response.use(
    (response: AxiosResponse<ApiResponse>) => {
      const body = response.data
      if (!body || typeof body !== 'object' || !('code' in body)) return response
      if (body.code === 0) return response
      const traceId = readTraceId(response.headers, body)
      throw new ApiError(body.message || '请求失败', body.code, response.status, traceId)
    },
    (error) => {
      const status: number = error?.response?.status || 0
      const traceId = readTraceId(error?.response?.headers, error?.response?.data)
        || error?.config?.headers?.['X-Trace-Id']
      if (status === 401) {
        const detail = normalizeErrorDetail(error?.response?.data?.detail)
        resolver.onUnauthorized()
        throw new ApiError(detail || '登录已失效，请重新登录', 401, 401, traceId)
      }
      if (status === 403 && !isAdminUrl(error?.config?.url)) {
        // 后端返回权限不足（学校端），统一跳 /403 页面
        resolver.onForbidden?.()
      }
      const msg =
        normalizeErrorDetail(error?.response?.data?.detail) ||
        error?.response?.data?.message ||
        error.message ||
        '网络异常'
      const text = typeof msg === 'string' ? msg : JSON.stringify(msg)
      if (import.meta.env.DEV && traceId) {
        console.warn(`[api] ${error?.config?.method} ${error?.config?.url} traceId=${traceId}`)
      }
      throw new ApiError(text, status, status, traceId)
    },
  )
  return http
}

/** 默认后端地址：优先运行时环境变量，其次 dev 代理 */
const baseURL: string = import.meta.env?.VITE_API_BASE_URL || '/api/v1'

export const http = createHttp(baseURL)

export function getApiBaseURL(): string {
  return baseURL
}

/** SSE 与普通 API 使用同一基址，开发环境交给已配置为不缓冲的 Vite 代理。 */
export function getSseApiBaseURL(): string {
  return baseURL
}

export function getAuthHeaders(): Record<string, string> {
  const token = resolver.getToken()
  const headers: Record<string, string> = {
    'X-School-Code': resolver.getSchoolCode(),
    'X-Trace-Id': newTraceId(),
  }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

/** 统一解包：Axios 已拦截，data 即业务 data */
export async function unwrap<T>(p: Promise<AxiosResponse<ApiResponse<T>>>): Promise<T> {
  const res = await p
  return res.data.data
}
