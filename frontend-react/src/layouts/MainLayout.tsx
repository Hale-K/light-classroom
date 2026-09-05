import { App, Dropdown } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '@/api'
import AssistantDock from '@/components/AssistantDock'
import Icon from '@/components/Icon'
import OnboardingGuide from '@/components/OnboardingGuide'
import { routeTitle } from '@/router/meta'
import { useAuthStore, selectDisplayName } from '@/store/auth'
import { APP_NAME } from '@/types'
import type { MenuNode } from '@/types'

const MENU_GROUP_ORDER = ['overview', 'school-affairs', 'teaching-exams']
const NAV_COLLAPSED_KEY = 'zh_nav_collapsed_groups'
const EXAM_MODULE_PATHS = ['/exam-rooms', '/exam-venues', '/exam-calendar', '/exam-invigilators', '/exam-scheduling']

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

function isNavItemActive(pathname: string, itemPath?: string | null): boolean {
  if (!itemPath) return false
  if (itemPath === '/exam-scheduling') {
    return EXAM_MODULE_PATHS.some((path) => pathname.startsWith(path))
  }
  return pathname.startsWith(itemPath)
}

function readCollapsedGroups(): Set<string> {
  try {
    const raw = localStorage.getItem(NAV_COLLAPSED_KEY)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((item): item is string => typeof item === 'string'))
  } catch {
    return new Set()
  }
}

function writeCollapsedGroups(collapsed: Set<string>) {
  localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify([...collapsed]))
}

/** 学校端主布局：3 组可折叠侧栏 + 顶栏 */
export default function MainLayout() {
  const { modal } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const schoolCode = useAuthStore((s) => s.schoolCode)
  const logout = useAuthStore((s) => s.logout)
  const [menus, setMenus] = useState<MenuNode[]>([])
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => readCollapsedGroups())

  useEffect(() => {
    authApi
      .menus()
      .then((res) => {
        const orderedMenus = [...res.menus].sort((a, b) => {
          const aIndex = MENU_GROUP_ORDER.indexOf(a.key)
          const bIndex = MENU_GROUP_ORDER.indexOf(b.key)
          return (aIndex === -1 ? MENU_GROUP_ORDER.length : aIndex) - (bIndex === -1 ? MENU_GROUP_ORDER.length : bIndex)
        })
        setMenus(orderedMenus)
      })
      .catch(() => setMenus([]))
  }, [])

  const activeGroupKey = useMemo(() => {
    for (const group of menus) {
      if ((group.children || []).some((item) => isNavItemActive(location.pathname, item.path))) {
        return group.key
      }
    }
    return null
  }, [location.pathname, menus])

  useEffect(() => {
    if (!activeGroupKey) return
    setCollapsedGroups((prev) => {
      if (!prev.has(activeGroupKey)) return prev
      const next = new Set(prev)
      next.delete(activeGroupKey)
      writeCollapsedGroups(next)
      return next
    })
  }, [activeGroupKey])

  const toggleGroup = useCallback((groupKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupKey)) {
        next.delete(groupKey)
      } else {
        next.add(groupKey)
      }
      writeCollapsedGroups(next)
      return next
    })
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

        <div className="menu-scroll">
          <nav className="nav" aria-label="主导航">
            {menus.map((group) => {
              const children = group.children || []
              if (children.length === 0) return null

              const renderNavItem = (item: MenuNode) => {
                const active = isNavItemActive(location.pathname, item.path)
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
                      <Icon name={item.icon} size={20} />
                    </span>
                    <span className="nav-label">{item.title}</span>
                    {!item.available && <span className="nav-lock">待开放</span>}
                  </button>
                )
              }

              // 仅一项时不显示分组标题（避免「工作台」重复出现）
              if (children.length === 1) {
                return (
                  <section key={group.key} className="nav-group nav-group-single">
                    {renderNavItem(children[0])}
                  </section>
                )
              }

              const collapsed = collapsedGroups.has(group.key)
              return (
                <section
                  key={group.key}
                  className={`nav-group${collapsed ? ' is-collapsed' : ''}`}
                >
                  <button
                    type="button"
                    className="nav-group-head"
                    aria-expanded={!collapsed}
                    onClick={() => toggleGroup(group.key)}
                  >
                    <span className="nav-caption">
                      <Icon name={group.key === 'school-affairs' ? 'school' : group.icon} size={14} />
                      <span>{group.title}</span>
                    </span>
                    <Icon name="chevron-down" size={14} className="nav-group-toggle" />
                  </button>
                  <div className="nav-group-body">
                    {children.map((item) => renderNavItem(item))}
                  </div>
                </section>
              )
            })}
          </nav>
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
          <div className="header-right">
            <OnboardingGuide />
            <Dropdown
              trigger={['click']}
              placement="bottomRight"
              menu={{
                items: [
                  {
                    key: 'who',
                    disabled: true,
                    label: (
                      <span className="account-who">
                        <span className="account-who-avatar">{(displayName || '师')[0]}</span>
                        <span className="account-who-copy">
                          <strong>{displayName || '未登录'}</strong>
                          <small>{roleLabel(user)}</small>
                        </span>
                      </span>
                    ),
                  },
                  {
                    key: 'school',
                    label: (
                      <span className="account-school" title="点击复制学校代码">
                        <span>当前学校</span>
                        <code>{schoolCode || '—'}</code>
                        <Icon name="clipboard" size={12} />
                      </span>
                    ),
                  },
                  { type: 'divider' },
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
                  if (key === 'school' && schoolCode) {
                    void navigator.clipboard.writeText(schoolCode).catch(() => undefined)
                    return
                  }
                  if (key === 'settings') navigate('/settings')
                  if (key === 'logout') onLogout()
                },
              }}
            >
              <button type="button" className="account-chip">
                <span className="account-chip-avatar">{(displayName || '师')[0]}</span>
                <span className="account-chip-copy">
                  <strong>{displayName || '未登录'}</strong>
                  <small>{roleLabel(user)}</small>
                </span>
                <Icon name="chevron-down" size={13} />
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
      <AssistantDock />
    </div>
  )
}
