import { App, Dropdown } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import Icon from '@/components/Icon'
import { routeTitle } from '@/router/meta'
import { useAdminStore } from '@/store/admin'

/** 平台超管布局：独立令牌隔离，侧栏仅学校管理 */
export default function AdminLayout() {
  const { modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const admin = useAdminStore((s) => s.admin)
  const logout = useAdminStore((s) => s.logout)

  const displayName = admin?.name || admin?.username || '超管'
  const onLogout = () => {
    modal.confirm({
      title: '退出登录',
      content: '确定退出平台管理后台吗？',
      okText: '退出',
      cancelText: '取消',
      onOk: () => {
        logout()
        navigate('/admin/login', { replace: true })
      },
    })
  }

  return (
    <div className="admin-root">
      <aside className="admin-aside">
        <div className="brand">
          <div className="brand-mark brand-mark-admin">管</div>
          <div className="brand-copy">
            <div className="brand-name">轻课堂 · 平台管理</div>
            <div className="brand-en">LightClass Platform</div>
          </div>
        </div>
        <nav className="nav">
          <button
            type="button"
            className={`nav-item${location.pathname.startsWith('/admin/schools') ? ' active' : ''}`}
            onClick={() => navigate('/admin/schools')}
          >
            <span className="nav-icon-wrap">
              <Icon name="users" size={18} />
            </span>
            <span className="nav-label">学校管理</span>
          </button>
        </nav>
      </aside>

      <div className="layout-content">
        <header className="layout-header app-header-glass">
          <div className="header-left">
            <div className="breadcrumb">
              <span>平台管理</span>
              <span className="breadcrumb-sep">/</span>
              <strong>{routeTitle(location.pathname) === '工作台' ? '学校管理' : routeTitle(location.pathname)}</strong>
            </div>
          </div>
          <div className="header-right">
            <span className="admin-name">超管 · {displayName}</span>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [{ key: 'logout', label: '退出登录' }],
                onClick: ({ key }) => key === 'logout' && onLogout(),
              }}
            >
              <button type="button" className="icon-btn" aria-label="更多操作">
                <Icon name="settings" size={17} />
              </button>
            </Dropdown>
          </div>
        </header>

        <main className="layout-main">
          <div className="page-shell page-enter" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
