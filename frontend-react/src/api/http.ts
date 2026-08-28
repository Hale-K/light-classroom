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
  constructor(message: string, code = -1, status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

/** 运行时读取 token / school_code，避免循环依赖与 import 时序问题 */
export interface AuthResolver {
  getToken: () => string | null
  getAdminToken: () => string | null
  getSchoolCode: () => string
  onUnauthorized: () => void
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
}
export function setAuthResolver(r: AuthResolver) {
  resolver = { ...resolver, ...r }
}

/** 判断是否为平台超管接口（/api/v1/admin/...） */
function isAdminUrl(url?: string): boolean {
  return !!url && url.startsWith('/admin')
}

function createHttp(baseURL: string): AxiosInstance {
  const http = axios.create({
    baseURL,
    timeout: 20000,
  })

  http.interceptors.request.use((config) => {
    // 平台超管路由用独立令牌，与学校端令牌隔离
    const token = isAdminUrl(config.url) ? resolver.getAdminToken() : resolver.getToken()
    if (token) config.headers.Authorization = `Bearer ${token}`
    config.headers['X-School-Code'] = resolver.getSchoolCode()
    return config
  })

  http.interceptors.response.use(
    (response: AxiosResponse<ApiResponse>) => {
      const body = response.data
      // 非标准结构（如文件流）直接返回
      if (!body || typeof body !== 'object' || !('code' in body)) return response
      if (body.code === 0) return response
      throw new ApiError(body.message || '请求失败', body.code, response.status)
    },
    (error) => {
      const status: number = error?.response?.status || 0
      if (status === 401) {
        resolver.onUnauthorized()
        throw new ApiError('登录已失效，请重新登录', 401, 401)
      }
      const msg =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error.message ||
        '网络异常'
      throw new ApiError(msg, status, status)
    },
  )
  return http
}

/** 默认后端地址：优先运行时环境变量，其次 dev 代理 */
const baseURL: string = import.meta.env?.VITE_API_BASE_URL || '/api/v1'

export const http = createHttp(baseURL)

/** 统一解包：Axios 已拦截，data 即业务 data */
export async function unwrap<T>(p: Promise<AxiosResponse<ApiResponse<T>>>): Promise<T> {
  const res = await p
  return res.data.data
}
