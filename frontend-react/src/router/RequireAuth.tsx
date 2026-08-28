import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

/**
 * 登录态路由守卫：无对应令牌时重定向登录页。
 * admin=true 走平台超管令牌（独立于学校端令牌）。
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
  return <>{children}</>
}
