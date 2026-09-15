import { create } from 'zustand'
import { adminApi } from '@/api'
import type { AdminSchool, PlatformAdminInfo } from '@/types'

const ADMIN_TOKEN_KEY = 'zh_admin_token'
const ADMIN_KEY = 'zh_admin_info'

function readAdmin(): PlatformAdminInfo | null {
  try {
    const raw = localStorage.getItem(ADMIN_KEY)
    return raw ? (JSON.parse(raw) as PlatformAdminInfo) : null
  } catch {
    return null
  }
}

interface AdminState {
  token: string
  admin: PlatformAdminInfo | null
  schools: AdminSchool[]
  login: (username: string, password: string) => Promise<void>
  fetchMe: () => Promise<void>
  loadSchools: () => Promise<void>
  createSchool: (data: {
    code: string
    name: string
    province: string
    gaokao_mode: '3+1+2' | '3+3' | 'traditional'
    admin_name: string
    admin_phone: string
    admin_password: string
  }) => Promise<void>
  updateSchool: (id: number, data: {
    name: string
    province?: string
    gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
    admin_phone?: string
  }) => Promise<void>
  resetPassword: (id: number, password: string) => Promise<void>
  toggleAdminStatus: (id: number) => Promise<void>
  logout: () => void
}

/** 平台超管身份（与学校端 auth store 完全隔离） */
export const useAdminStore = create<AdminState>()((set, get) => ({
  token: localStorage.getItem(ADMIN_TOKEN_KEY) || '',
  admin: readAdmin(),
  schools: [],
  async login(username, password) {
    const data = await adminApi.login(username, password)
    localStorage.setItem(ADMIN_TOKEN_KEY, data.access_token)
    localStorage.setItem(ADMIN_KEY, JSON.stringify(data.admin))
    set({ token: data.access_token, admin: data.admin })
  },
  async fetchMe() {
    try {
      const admin = await adminApi.me()
      localStorage.setItem(ADMIN_KEY, JSON.stringify(admin))
      set({ admin })
    } catch {
      /* 失效交给拦截器/守卫处理 */
    }
  },
  async loadSchools() {
    const schools = await adminApi.listSchools()
    set({ schools })
  },
  async createSchool(data) {
    await adminApi.createSchool(data)
    await get().loadSchools()
  },
  async updateSchool(id, data) {
    await adminApi.updateSchool(id, data)
    await get().loadSchools()
  },
  async resetPassword(id, password) {
    await adminApi.resetPassword(id, password)
  },
  async toggleAdminStatus(id) {
    await adminApi.toggleAdminStatus(id)
    await get().loadSchools()
  },
  logout() {
    localStorage.removeItem(ADMIN_TOKEN_KEY)
    localStorage.removeItem(ADMIN_KEY)
    set({ token: '', admin: null, schools: [] })
  },
}))
