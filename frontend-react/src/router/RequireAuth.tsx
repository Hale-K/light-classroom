import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'
import { routeRoles } from './meta'

/**
 * 学校端路由守卫：
 * 1) 无 token → 跳 /login
 * 2) activeRole 不在路由允许列表里 → 跳 /403（保留访问源在 state.from）
 *
 * 平台超管端（admin=true）只检查 token，角色由后端接口自身校验。
 */
export default function RequireAuth({
  admin = false,
  children,
}: {
  admin?: boolean
  children: ReactNode
}) {
  const location = useLocation()
  const token = admin
    ? localStorage.getItem('zh_admin_token')
    : localStorage.getItem('zh_token')

  if (!token) {
    return (
      <Navigate
        to={admin ? '/admin/login' : '/login'}
        replace
        state={{ from: location.pathname + location.search }}
      />
    )
  }

  // 学校端：角色校验
  if (!admin) {
    const user = useAuthStore.getState().user
    const activeRole = useAuthStore.getState().activeRole
    const allowed = routeRoles(location.pathname)
    if (allowed) {
      const roleToCheck = activeRole || user?.role
      if (!roleToCheck || !allowed.includes(roleToCheck)) {
        return (
          <Navigate
            to="/403"
            replace
            state={{ from: location.pathname + location.search }}
          />
        )
      }
    }
  }

  return <>{children}</>
}
