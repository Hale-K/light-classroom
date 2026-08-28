import { App, Dropdown } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '@/api'
import Icon from '@/components/Icon'
import { routeTitle } from '@/router/meta'
import { useAuthStore, selectDisplayName } from '@/store/auth'
import { APP_NAME } from '@/types'
import type { MenuNode } from '@/types'

/** 当前学年·学期（8 月前后切换） */
function academicTerm(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth() + 1
  const startYear = month >= 8 ? year : year - 1
  const term = month >= 2 && month < 8 ? 2 : 1
  return `${startYear}—${startYear + 1} 学年 · 第 ${term} 学期`
}

function roleLabel(user: { role?: string; roles?: string[] } | null): string {
  if (!user) return '任教老师'
  if (user.role === 'director') return '校长管理员'
  if (user.roles?.includes('academic_director')) return '教导主任'
  if (user.roles?.includes('head_teacher')) return '班主任'
  return '任教老师'
}

/** 学校端主布局：后端菜单分组侧栏 + 顶栏（面包屑/学期/账号） */
export default function MainLayout() {
  const { modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const schoolCode = useAuthStore((s) => s.schoolCode)
  const logout = useAuthStore((s) => s.logout)
  const [menus, setMenus] = useState<MenuNode[]>([])
  const [themeMode, setThemeMode] = useState<'minimal' | 'tech'>(() => {
    return localStorage.getItem('zh_theme') === 'tech' ? 'tech' : 'minimal'
  })

  useEffect(() => {
    document.body.dataset.theme = themeMode
    localStorage.setItem('zh_theme', themeMode)
  }, [themeMode])

  useEffect(() => {
    authApi
      .menus()
        .then((res) => {
          // 系统设置改为左下角入口，不再占用侧边菜单
        const menuOrder = ['overview', 'school', 'staffing', 'resources', 'enrollment', 'placement', 'teaching', 'exams', 'collaboration']
        const orderedMenus = [...res.menus].sort((a, b) => {
          const aIndex = menuOrder.indexOf(a.key)
          const bIndex = menuOrder.indexOf(b.key)
          return (aIndex === -1 ? menuOrder.length : aIndex) - (bIndex === -1 ? menuOrder.length : bIndex)
        })
        setMenus(orderedMenus)
      })
      .catch(() => setMenus([]))
  }, [])

  const displayName = useMemo(() => selectDisplayName({ user } as never), [user])
  const currentTitle = routeTitle(location.pathname)

  const onLogout = () => {
    modal.confirm({
      title: '退出登录',
      content: '确定退出当前工作台吗？',
      okText: '退出工作台',
      cancelText: '继续使用',
      onOk: () => {
        logout()
        navigate('/login', { replace: true })
      },
    })
  }

  return (
    <div className="layout-root">
      <aside className="layout-aside">
        <div className="brand">
          <div className="brand-mark">
            <span>轻</span>
          </div>
          <div className="brand-copy">
            <div className="brand-name">{APP_NAME}</div>
            <div className="brand-en">轻课堂教务系统</div>
          </div>
        </div>

        <div className="workspace-switcher">
          <div className="workspace-info">
            <div className="workspace-label">当前学校</div>
            <div className="workspace-value">{schoolCode || '—'}</div>
          </div>
          <Icon name="chevron-down" size={14} className="workspace-chevron" />
        </div>

        <div className="menu-scroll">
          <nav className="nav" aria-label="主导航">
            {menus.map((group) => (
              <section key={group.key} className="nav-group">
                <h2 className="nav-caption">
                  <Icon name={group.icon} size={12} />
                  <span>{group.title}</span>
                </h2>
                {(group.children || []).map((item) => {
                  const examModulePaths = ['/exam-rooms', '/exam-venues', '/exam-calendar', '/exam-invigilators', '/exam-scheduling']
                  const active = item.path === '/exam-scheduling'
                    ? examModulePaths.some((path) => location.pathname.startsWith(path))
                    : !!item.path && location.pathname.startsWith(item.path)
                  const targetPath = item.path === '/exam-scheduling' ? '/exam-rooms' : item.path
                  return (
                    <button
                      key={item.key}
                      type="button"
                      className={`nav-item${active ? ' active' : ''}`}
                      disabled={!item.available}
                      onClick={() => targetPath && item.available && navigate(targetPath)}
                    >
                      <span className="nav-icon-wrap">
                        <Icon name={item.icon} size={17} />
                      </span>
                      <span className="nav-label">{item.title}</span>
                      {!item.available && <span className="nav-lock">待开放</span>}
                    </button>
                  )
                })}
              </section>
            ))}
          </nav>
        </div>

        <div className="aside-bottom">
          <Dropdown
            trigger={['click']}
            placement="topLeft"
            menu={{
              items: [
                {
                  key: 'settings',
                  icon: <Icon name="settings" size={14} />,
                  label: '系统设置',
                },
                { type: 'divider' },
                {
                  key: 'logout',
                  icon: <Icon name="logout" size={14} />,
                  label: '退出登录',
                },
              ],
              onClick: ({ key }) => {
                if (key === 'settings') navigate('/settings')
                if (key === 'logout') onLogout()
              },
            }}
          >
            <button type="button" className="account-dock">
              <span className="dock-avatar">
                {(displayName || '师')[0]}
                <i />
              </span>
              <span className="dock-copy">
                <strong>{displayName || '未登录'}</strong>
                <small>{roleLabel(user)}</small>
              </span>
              <Icon name="chevron-down" size={13} className="dock-chevron" />
            </button>
          </Dropdown>
        </div>
      </aside>

      <div className="layout-content">
        <header className="layout-header app-header-glass">
          <div className="header-left">
            <div className="breadcrumb">
              <span>轻课堂</span>
              <span className="breadcrumb-sep">/</span>
              <strong>{currentTitle}</strong>
            </div>
            <span className="header-context">{academicTerm()}</span>
          </div>
          <button
            type="button"
            className="theme-toggle"
            aria-label={themeMode === 'tech' ? '切换到极简主题' : '切换到科技主题'}
            onClick={() => setThemeMode((current) => current === 'tech' ? 'minimal' : 'tech')}
          >
            <Icon name={themeMode === 'tech' ? 'dashboard' : 'sparkles'} size={15} />
            <span>{themeMode === 'tech' ? '极简主题' : '科技主题'}</span>
          </button>
        </header>

        <main className="layout-main">
          <div className="page-shell page-enter" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      </div>

      {/* 左下角用户区已嵌入侧边栏 aside-bottom */}

    </div>
  )
}
