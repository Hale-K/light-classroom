import { Navigate, useSearchParams } from 'react-router-dom'

/** 旧「角色管理」入口：收敛到统一工作台 */
export default function RolesView() {
  const [params] = useSearchParams()
  const role = params.get('role')
  return (
    <Navigate
      to={role ? `/rbac?role=${encodeURIComponent(role)}` : '/rbac'}
      replace
    />
  )
}
