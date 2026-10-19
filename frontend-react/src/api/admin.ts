/** admin 领域 API（由 api/index.ts 拆分）。 */
import type {
  AdminSchool,
  EducationStage,
  GaokaoMode,
  PlatformAdminInfo,
} from '@/types'
import { http, unwrap } from './http'

export const adminApi = {
    login: (username: string, password: string) =>
    unwrap<{ access_token: string; token_type: string; admin: PlatformAdminInfo }>(
      http.post('/admin/login', { username, password }),
    ),
  me: () => unwrap<PlatformAdminInfo>(http.get('/admin/me')),
  listSchools: () => unwrap<AdminSchool[]>(http.get('/admin/schools')),
  createSchool: (data: {
    code: string
    name: string
    province: string
    education_stage: EducationStage
    gaokao_mode?: GaokaoMode
    admin_name: string
    admin_phone: string
    admin_password: string
  }) => unwrap<AdminSchool>(http.post('/admin/schools', data)),
  updateSchool: (id: number, data: {
    name: string
    province?: string
    gaokao_mode?: GaokaoMode
    admin_phone?: string
  }) => unwrap<AdminSchool>(http.put(`/admin/schools/${id}`, data)),
  resetPassword: (id: number, password: string) =>
    unwrap<{ school_id: number; phone: string | null }>(
      http.post(`/admin/schools/${id}/reset-password`, { password }),
    ),
  toggleAdminStatus: (id: number) =>
    unwrap<{ school_id: number; frozen: boolean }>(
      http.post(`/admin/schools/${id}/admin-status`),
    ),
  schoolStats: () => unwrap<{ total: number }>(http.get('/admin/schools/stats')),
}

