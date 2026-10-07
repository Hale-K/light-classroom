/**
 * 各业务领域 API 模块（对接 FastAPI 后端 /api/v1 真实端点）。
 * 每个文件一个领域：auth/组织/设施/排课/走班/考试/RBAC/文件/AI……
 * 此文件仅做统一出口，业务代码统一 `from '@/api'` 引用。
 */
export * from './auth'
export * from './admin'
export * from './org'
export * from './facility'
export * from './scheduling'
export * from './gaokao'
export * from './seating'
export * from './exams'
export * from './dashboard'
export * from './rbac'
export * from './files'
export * from './teacherProfiles'
export * from './ai'
export * from './onboarding'

export type { AuthResolver } from './http'
