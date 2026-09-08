import { create } from 'zustand'
import { authApi } from '@/api'
import { DEFAULT_SCHOOL_CODE } from '@/types'
import type { UserInfo } from '@/types'

const TOKEN_KEY = 'zh_token'
const USER_KEY = 'zh_user'
const SCHOOL_KEY = 'zh_school_code'
const ACTIVE_ROLE_KEY = 'zh_active_role'

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
  /** 当前生效角色：user.roles 中的一个，用于菜单/数据过滤。非多角色用户此值为 null */
  activeRole: string | null
  login: (phone: string, password: string) => Promise<void>
  fetchMe: () => Promise<void>
  setSchoolCode: (code: string) => void
  setActiveRole: (role: string) => void
  logout: () => void
}

/** 根据 user 的 roles + localStorage 选一个生效角色 */
function resolveActiveRole(user: UserInfo | null): string | null {
  if (!user) return null
  const roles = user.roles || (user.role ? [user.role] : [])
  if (roles.length <= 1) return null // 只有一个角色，不用切换
  const saved = localStorage.getItem(ACTIVE_ROLE_KEY)
  if (saved && roles.includes(saved)) return saved
  // 默认：有 head_teacher 就优先选（更严格的视角），否则选第一个
  return roles.includes('head_teacher') ? 'head_teacher' : roles[0]
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: readUser(),
  schoolCode: normalizeSchoolCode(localStorage.getItem(SCHOOL_KEY) || ''),
  activeRole: resolveActiveRole(readUser()),
  async login(phone, password) {
    const data = await authApi.login(phone, password)
    const schoolCode = normalizeSchoolCode(data.school?.code || get().schoolCode)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
    localStorage.setItem(SCHOOL_KEY, schoolCode)
    const activeRole = resolveActiveRole(data.user)
    if (activeRole) localStorage.setItem(ACTIVE_ROLE_KEY, activeRole)
    set({ token: '', user: data.user, schoolCode, activeRole })
  },
  async fetchMe() {
    try {
      const user = await authApi.me()
      localStorage.setItem(USER_KEY, JSON.stringify(user))
      const activeRole = resolveActiveRole(user)
      if (activeRole) localStorage.setItem(ACTIVE_ROLE_KEY, activeRole)
      set({ user, activeRole })
    } catch {
      /* 未登录/失效交给拦截器处理 */
    }
  },
  setSchoolCode(code) {
    const schoolCode = normalizeSchoolCode(code)
    localStorage.setItem(SCHOOL_KEY, schoolCode)
    set({ schoolCode })
  },
  setActiveRole(role) {
    const user = get().user
    const roles = user?.roles || (user?.role ? [user.role] : [])
    if (!roles.includes(role)) return
    localStorage.setItem(ACTIVE_ROLE_KEY, role)
    set({ activeRole: role })
  },
  logout() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(ACTIVE_ROLE_KEY)
    set({ token: '', user: null, activeRole: null })
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
