import { App, Button, Dropdown, Result, Segmented, Spin } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { authApi, type AcademicYearsSettings } from '@/api'
import AssistantDock from '@/components/AssistantDock'
import Icon from '@/components/Icon'
import OnboardingGuide from '@/components/OnboardingGuide'
import PageTour from '@/components/PageTour'
import { routeRoles, routeTitle } from '@/router/meta'
import { useAuthStore, selectDisplayName } from '@/store/auth'
import { APP_NAME } from '@/types'
import type { MenuNode } from '@/types'
import { ACADEMIC_CONTEXT_CHANGED } from '@/utils/academicContext'

const MENU_GROUP_ORDER = ['overview', 'school-affairs', 'teaching-exams']
const NAV_COLLAPSED_KEY = 'zh_nav_collapsed_groups'
const EXAM_MODULE_PATHS = ['/exam-venues', '/exam-calendar', '/exam-invigilators', '/exam-scheduling']
const MENU_GATED_PATHS = new Set([
  '/dashboard', '/scheduling', '/teacher-courses', '/teacher-preparation', '/teacher-classes', '/teacher-students',
  '/file-center', '/ai-providers', '/students', '/classes', '/staff', '/rbac', '/gaokao', '/seating',
  '/exam-scheduling', '/settings', '/subjects', '/campus-buildings',
  '/teacher-profiles', '/teacher-grades', '/teacher-notices',
])

/**
 * 后端数据库 seed 的 path 映射覆盖表。
 * 迁移前临时用：key 是菜单 key，value 是期望的前端路径。
 */
const MENU_PATH_OVERRIDE: Record<string, string> = {
  'teacher-preparation': '/teacher-preparation',
  'teacher-classes': '/teacher-classes',
  'teacher-students': '/teacher-students',
}
const MENU_NAME_OVERRIDE: Record<string, string> = {
  'teacher-classes': '学生管理',
  'teacher-students': '选课审核',
}
function requiredMenuPath(pathname: string): string | null {
  if (pathname === '/' || pathname === '/onboarding') return null
  if (EXAM_MODULE_PATHS.includes(pathname)) return '/exam-scheduling'
  if (pathname === '/rooms') return '/campus-buildings'
  if (pathname === '/organization' || pathname === '/staff-positions') return '/staff'
  if (pathname === '/roles' || pathname === '/permissions') return '/rbac'
  return MENU_GATED_PATHS.has(pathname) ? pathname : null
}

function academicTerm(settings: AcademicYearsSettings | null): string {
  if (!settings?.current_academic_year) return '学年学期读取中'
  return `${settings.current_academic_year} 学年 · 第 ${settings.current_term} 学期`
}

/** 角色展示名：优先用当前生效角色（activeRole），否则回退 user.role */
function roleLabel(effectiveRole?: string | null): string {
  if (!effectiveRole) return '任教老师'
  switch (effectiveRole) {
    case 'director': return '校长管理员'
    case 'school_admin': return '学校管理员'
    case 'academic_director': return '教导主任'
    case 'head_teacher': return '班主任'
    case 'teacher': return '任课教师'
    default: return effectiveRole
  }
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
  const activeRole = useAuthStore((s) => s.activeRole)
  const setActiveRole = useAuthStore((s) => s.setActiveRole)
  const [menus, setMenus] = useState<MenuNode[]>([])
  const [academicSettings, setAcademicSettings] = useState<AcademicYearsSettings | null>(null)
  const [menusLoaded, setMenusLoaded] = useState(false)
  const [menusError, setMenusError] = useState(false)
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => readCollapsedGroups())

  useEffect(() => {
    setMenusLoaded(false)
    authApi
      .menus()
      .then((res) => {
        const orderedMenus = [...res.menus].sort((a, b) => {
          const aIndex = MENU_GROUP_ORDER.indexOf(a.key)
          const bIndex = MENU_GROUP_ORDER.indexOf(b.key)
          return (aIndex === -1 ? MENU_GROUP_ORDER.length : aIndex) - (bIndex === -1 ? MENU_GROUP_ORDER.length : bIndex)
        }).map((group) => ({
          ...group,
          children: (group.children || []).map((item) => ({
            ...item,
            title: MENU_NAME_OVERRIDE[item.key] || item.title,
            path: MENU_PATH_OVERRIDE[item.key] || item.path,
          })),
        }))
        setMenus(orderedMenus)
        setMenusError(false)
      })
      .catch(() => {
        setMenus([])
        setMenusError(true)
      })
      .finally(() => setMenusLoaded(true))
  }, [activeRole])

  const refreshAcademicSettings = useCallback(() => {
    let active = true
    authApi.academicYears()
      .then((settings) => {
        if (active) setAcademicSettings(settings)
      })
      .catch(() => {
        if (active) setAcademicSettings(null)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    refreshAcademicSettings()
    window.addEventListener(ACADEMIC_CONTEXT_CHANGED, refreshAcademicSettings)
    return () => window.removeEventListener(ACADEMIC_CONTEXT_CHANGED, refreshAcademicSettings)
  }, [refreshAcademicSettings])

  const effectiveRole = activeRole || user?.role
  // 教师工作台模式：任课教师视角，不显示教导主任+的高级菜单
  const teacherMode = effectiveRole === 'teacher'

  /** 按当前生效角色过滤菜单：children 里 roleRoles(path) 不包含当前角色的剔除，group 变空也整块移除 */
  const visibleMenus = useMemo(() => {
    if (!effectiveRole) return menus
    return menus
      .map((group) => ({
        ...group,
        children: (group.children || []).filter((item) => {
          if (['scans', 'meetings', 'teacher-research', 'exams', 'teacher-homework'].includes(item.key)) return false
          if (!item.path) return false
          const allowed = routeRoles(item.path)
          // undefined = 所有登录用户可进；否则要求当前角色在允许列表里
          return !allowed || allowed.includes(effectiveRole)
        }),
      }))
      .filter((group) => (group.children || []).length > 0)
  }, [menus, effectiveRole])

  const allowedMenuPaths = useMemo(
    () => new Set(visibleMenus.flatMap((group) => (group.children || []).map((item) => item.path).filter(Boolean) as string[])),
    [visibleMenus],
  )
  const gatePath = requiredMenuPath(location.pathname)
  const routeAllowed = gatePath === null || allowedMenuPaths.has(gatePath)

  const activeGroupKey = useMemo(() => {
    for (const group of visibleMenus) {
      if ((group.children || []).some((item) => isNavItemActive(location.pathname, item.path))) {
        return group.key
      }
    }
    return null
  }, [location.pathname, visibleMenus])

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
    <div className={`layout-root${teacherMode ? ' teacher-desk-layout' : ''}`}>
      <aside className="layout-aside">
        <div className="brand">
          <div className="brand-mark">
            <span>轻</span>
          </div>
          <div className="brand-copy">
            <div className="brand-name">{teacherMode ? '教师工作台' : APP_NAME}</div>
            <div className="brand-en">轻课堂教务系统</div>
          </div>
        </div>

        <div className="menu-scroll">
          <nav className="nav" aria-label="主导航">
            {visibleMenus.map((group) => {
              const children = group.children || []
              if (children.length === 0) return null

              const renderNavItem = (item: MenuNode) => {
                const active = isNavItemActive(location.pathname, item.path)
                const targetPath = item.path
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
            <span className="header-context">{academicTerm(academicSettings)}</span>
          </div>
          <div className="header-right">
            {teacherMode &&
              (() => {
                const roles = user?.roles || (user?.role ? [user.role] : [])
                /** 能切换的角色集合：教师端只关心 teacher ↔ head_teacher */
                const switchable = roles.filter((r) => ['teacher', 'head_teacher'].includes(r))
                if (switchable.length < 2) {
                  // 只有一个角色，仅展示标签
                  const label = switchable.includes('head_teacher') ? '班主任' : '任课教师'
                  return <span className="td-role-label">{label}</span>
                }
                const options = [
                  { label: '任课教师', value: 'teacher' },
                  { label: '班主任', value: 'head_teacher' },
                ].filter((o) => switchable.includes(o.value))
                return (
                  <Segmented
                    size="small"
                    options={options}
                    value={activeRole || switchable[0]}
                    onChange={(v) => setActiveRole(v as string)}
                  />
                )
              })()}
            <PageTour />
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
                          <small>{roleLabel(effectiveRole)}</small>
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
                  <small>{roleLabel(effectiveRole)}</small>
                </span>
                <Icon name="chevron-down" size={13} />
              </button>
            </Dropdown>
          </div>
        </header>

        <main className="layout-main">
          <div className="page-shell page-enter" key={location.pathname}>
            {!menusLoaded ? (
              <div style={{ padding: 48, textAlign: 'center' }}><Spin tip="正在校验页面权限" /></div>
            ) : menusError ? (
              <Result status="warning" title="菜单权限加载失败" subTitle="暂时无法校验页面访问权限，请刷新后重试。" extra={<Button onClick={() => window.location.reload()}>刷新页面</Button>} />
            ) : routeAllowed ? (
              <Outlet />
            ) : (
              <Result status="403" title="无权访问此页面" subTitle="当前角色未配置该菜单权限。" extra={<Button type="primary" onClick={() => navigate('/dashboard', { replace: true })}>返回工作台</Button>} />
            )}
          </div>
        </main>
      </div>
      <AssistantDock />
    </div>
  )
}

