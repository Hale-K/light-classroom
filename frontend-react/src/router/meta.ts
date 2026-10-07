/** 路由元数据中心：每个路由的页面标题 + 允许访问的角色。
 * 未在此表出现的路由：允许所有登录用户访问（除非 ROLES_MAP 另有规则）。
 *
 * 角色键使用 user.roles 数组中的值：
 *   director         校长 / 学校创建者
 *   school_admin     学校管理员
 *   academic_director 教导主任
 *   head_teacher     班主任
 *   teacher          任课教师
 */

export interface RouteMeta {
  /** 页面标题（面包屑 / 顶栏） */
  title: string
  /** 允许访问的角色，undefined = 所有登录用户可访问 */
  roles?: string[]
}

export const ROUTE_META: Record<string, RouteMeta> = {
  // —— 工作台 & 教师端（所有登录用户） ——
  '/dashboard': { title: '工作台' },
  '/teacher-courses': { title: '课程' },
  '/teacher-profiles': { title: '教师档案', roles: ['academic_director', 'school_admin', 'director'] },
  '/teacher-grades': { title: '成绩' },
  '/teacher-notices': { title: '通知' },
  '/students': { title: '学生档案', roles: ['academic_director', 'school_admin', 'director'] },
  '/file-center': { title: '文件中心', roles: ['academic_director', 'school_admin', 'director'] },
  '/teacher-preparation': { title: '备课' },
  '/teacher-classes': { title: '学生管理' },
  '/teacher-students': { title: '选课审核' },
  '/onboarding': { title: '新手引导' },
  '/seating': { title: '班级排座', roles: ['head_teacher', 'academic_director', 'school_admin', 'director'] },
  '/classes': { title: '行政班管理', roles: ['head_teacher', 'academic_director', 'school_admin', 'director'] },

  // —— 教导主任+（含校长、管理员） ——
  '/scheduling': { title: '排课管理', roles: ['academic_director', 'school_admin', 'director'] },
  '/subjects': { title: '科目管理', roles: ['academic_director', 'school_admin', 'director'] },
  '/campus-buildings': { title: '空间资源', roles: ['academic_director', 'school_admin', 'director'] },
  '/gaokao': { title: '学生选课', roles: ['head_teacher', 'academic_director', 'school_admin', 'director'] },
  '/staff': { title: '人员账号', roles: ['academic_director', 'school_admin', 'director'] },
  '/exam-scheduling': { title: '排考管理', roles: ['academic_director', 'school_admin', 'director'] },
  '/exam-venues': { title: '考场安排', roles: ['academic_director', 'school_admin', 'director'] },
  '/exam-calendar': { title: '考试日程', roles: ['academic_director', 'school_admin', 'director'] },
  '/exam-invigilators': { title: '监考教师', roles: ['academic_director', 'school_admin', 'director'] },

  // —— 校长 / 超管专属 ——
  '/rbac': { title: '角色与权限', roles: ['director'] },
  '/roles': { title: '角色与权限', roles: ['director'] },
  '/permissions': { title: '角色与权限', roles: ['director'] },
  '/settings': { title: '系统设置', roles: ['director'] },
  '/staff-positions': { title: '岗位与权限', roles: ['director', 'school_admin'] },
  '/ai-providers': { title: '服务商管理', roles: ['academic_director', 'school_admin', 'director'] },
  '/knowledge': { title: '知识库', roles: ['academic_director', 'school_admin', 'director'] },
}

/**
 * 取当前路由元数据：精确匹配优先，否则按前缀匹配动态路由。
 * 找不到则返回默认值。
 */
export function getRouteMeta(path: string): RouteMeta {
  if (ROUTE_META[path]) return ROUTE_META[path]
  // 子路径匹配：/foo/bar 也算 /foo
  for (const [prefix, meta] of Object.entries(ROUTE_META)) {
    if (path.startsWith(prefix + '/')) return meta
  }
  return { title: '工作台' }
}

/** 取路由标题，等价于之前的 routeTitle */
export function routeTitle(path: string): string {
  return getRouteMeta(path).title
}

/** 取某路径要求的角色列表，undefined = 不限角色 */
export function routeRoles(path: string): string[] | undefined {
  return getRouteMeta(path).roles
}
