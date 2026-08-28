import { defineStore } from 'pinia'
import { authApi } from '@zhiheng/api'
import { DEFAULT_SCHOOL_CODE } from '@zhiheng/shared'
import type { UserInfo } from '@zhiheng/shared'

const TOKEN_KEY = 'zh_token'
const USER_KEY = 'zh_user'
const SCHOOL_KEY = 'zh_school_code'

/** 归一化历史残留值（早期前端默认 'default'，与后端租户 'demo' 不一致） */
function normalizeSchoolCode(code: string): string {
  const c = (code || '').trim()
  if (!c || c === 'default') return DEFAULT_SCHOOL_CODE
  return c
}

function readUser(): UserInfo | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as UserInfo) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: readUser(),
    schoolCode: normalizeSchoolCode(localStorage.getItem(SCHOOL_KEY) || ''),
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    /** 展示用姓名：遇到乱码/占位符时按角色降级，避免「欢迎回来，???」 */
    displayName: (s): string => {
      const u = s.user
      if (!u) return ''
      const n = (u.name || '').trim()
      if (!n || /[?]|[\uFFFD]/.test(n)) {
        return u.role === 'director' ? '校长' : u.role === 'teacher' ? '老师' : '老师'
      }
      return n
    },
  },
  actions: {
    async login(phone: string, password: string) {
      const data = await authApi.login(phone, password)
      this.token = data.access_token
      this.user = data.user
      // 登录后由后端返回账号所属学校，写入本机以便后续请求带上正确的学校代码
      this.schoolCode = normalizeSchoolCode(data.school?.code || this.schoolCode)
      localStorage.setItem(TOKEN_KEY, this.token)
      localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      localStorage.setItem(SCHOOL_KEY, this.schoolCode)
    },
    async fetchMe() {
      try {
        this.user = await authApi.me()
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      } catch {
        /* 未登录/失效交给拦截器处理 */
      }
    },
    setSchoolCode(code: string) {
      this.schoolCode = normalizeSchoolCode(code)
      localStorage.setItem(SCHOOL_KEY, this.schoolCode)
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})