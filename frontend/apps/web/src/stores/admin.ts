import { defineStore } from 'pinia'
import { adminApi } from '@zhiheng/api'
import type { AdminSchool, PlatformAdminInfo } from '@zhiheng/shared'

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

/** 平台超管身份（与学校端 auth store 完全隔离） */
export const useAdminStore = defineStore('admin', {
  state: () => ({
    token: localStorage.getItem(ADMIN_TOKEN_KEY) || '',
    admin: readAdmin(),
    schools: [] as AdminSchool[],
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
  },
  actions: {
    async login(username: string, password: string) {
      const data = await adminApi.login(username, password)
      this.token = data.access_token
      this.admin = data.admin
      localStorage.setItem(ADMIN_TOKEN_KEY, this.token)
      localStorage.setItem(ADMIN_KEY, JSON.stringify(this.admin))
    },
    async fetchMe() {
      try {
        this.admin = await adminApi.me()
        localStorage.setItem(ADMIN_KEY, JSON.stringify(this.admin))
      } catch {
        /* 失效交给拦截器/守卫处理 */
      }
    },
    async loadSchools() {
      this.schools = await adminApi.listSchools()
    },
    async createSchool(data: {
      code: string
      name: string
      province: string
      gaokao_mode: '3+1+2' | '3+3' | 'traditional'
      admin_name: string
      admin_phone: string
      admin_password: string
    }) {
      await adminApi.createSchool(data)
      await this.loadSchools()
    },
    async updateSchool(id: number, data: {
      name: string
      province?: string
      gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
      admin_phone?: string
    }) {
      await adminApi.updateSchool(id, data)
      await this.loadSchools()
    },
    async resetPassword(id: number, password: string) {
      await adminApi.resetPassword(id, password)
    },
    logout() {
      this.token = ''
      this.admin = null
      this.schools = []
      localStorage.removeItem(ADMIN_TOKEN_KEY)
      localStorage.removeItem(ADMIN_KEY)
    },
  },
})
