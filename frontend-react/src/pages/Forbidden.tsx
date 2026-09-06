import { Button, Result } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'

/**
 * 403 无权访问页：
 * - 路由守卫跳过来时，state.from 里带了原本想去的路径
 * - API 403 拦截跳过来时，state.from 也会带上
 *
 * 提供"返回首页"和"申请权限"两个操作。
 */
export default function ForbiddenPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const activeRole = useAuthStore((s) => s.activeRole)

  const from = ((location.state as { from?: string } | null)?.from) || '/'
  const roleLabel = activeRole || user?.role || '未登录'

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-soft, #f5f5f5)',
      }}
    >
      <Result
        status="403"
        title="403"
        subTitle={
          <div style={{ lineHeight: 1.8 }}>
            <div>抱歉，你当前的角色没有权限访问这个页面。</div>
            <div style={{ color: 'var(--text-tertiary, #999)' }}>
              当前角色：<b>{roleLabel}</b> · 想去的页面：<code>{from}</code>
            </div>
          </div>
        }
        extra={[
          <Button key="back" type="primary" onClick={() => navigate('/dashboard', { replace: true })}>
            返回工作台
          </Button>,
          <Button key="retry" onClick={() => navigate(from)}>
            再试一次
          </Button>,
        ]}
      />
    </div>
  )
}
