import { create } from 'zustand'
import { authApi } from '@/api'
import { DEFAULT_SCHOOL_CODE } from '@/types'
import type { UserInfo } from '@/types'

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

interface AuthState {
  token: string
  user: UserInfo | null
  schoolCode: string
  login: (phone: string, password: string) => Promise<void>
  fetchMe: () => Promise<void>
  setSchoolCode: (code: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: readUser(),
  schoolCode: normalizeSchoolCode(localStorage.getItem(SCHOOL_KEY) || ''),
  async login(phone, password) {
    const data = await authApi.login(phone, password)
    // 登录后由后端返回账号所属学校，写入本机以便后续请求带上正确的学校代码
    const schoolCode = normalizeSchoolCode(data.school?.code || get().schoolCode)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
    localStorage.setItem(SCHOOL_KEY, schoolCode)
    set({ token: data.access_token, user: data.user, schoolCode })
  },
  async fetchMe() {
    try {
      const user = await authApi.me()
      localStorage.setItem(USER_KEY, JSON.stringify(user))
      set({ user })
    } catch {
      /* 未登录/失效交给拦截器处理 */
    }
  },
  setSchoolCode(code) {
    const schoolCode = normalizeSchoolCode(code)
    localStorage.setItem(SCHOOL_KEY, schoolCode)
    set({ schoolCode })
  },
  logout() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    set({ token: '', user: null })
  },
}))

/** 展示用姓名：遇到乱码/占位符时按角色降级，避免「欢迎回来，???」 */
export const selectDisplayName = (s: AuthState): string => {
  const u = s.user
  if (!u) return ''
  const n = (u.name || '').trim()
  if (!n || /[?]|[\uFFFD]/.test(n)) {
    return u.role === 'director' ? '校长' : '老师'
  }
  return n
}
