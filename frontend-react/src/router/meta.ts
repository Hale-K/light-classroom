/** 路由 -> 页面标题（面包屑 / 顶栏使用，与 Vue 版 route.meta.title 对齐） */
const TITLE_MAP: Record<string, string> = {
  '/dashboard': '工作台',
  '/ai-providers': '服务商管理',
  '/exams': '试卷库',
  '/scans': '扫描进卷',
  '/scheduling': '排课管理',
  '/onboarding': '新手引导',
  '/file-center': '文件中心',
  '/students': '学生档案',
  '/classes': '行政班管理',
  '/organization': '组织机构',
  '/staff': '人员账号',
  '/staff-positions': '岗位与权限',
  '/rbac': '角色与权限',
  '/roles': '角色与权限',
  '/permissions': '角色与权限',
  '/gaokao': '学生选课',
  '/seating': '班级排座',
  '/exam-scheduling': '排考管理',
  '/exam-rooms': '考场管理',
  '/exam-venues': '考场安排',
  '/exam-calendar': '考试日程',
  '/exam-invigilators': '监考教师',
  '/settings': '系统设置',
  '/subjects': '科目管理',
  '/campus-buildings': '空间资源',
  '/rooms': '场室资源',
  '/meetings': '会议管理',
  '/stats': '成绩统计',
  '/teacher-profiles': '教师档案',
}

/** 取当前路由标题：精确匹配，否则按前缀匹配动态路由（grading/:paperId 等） */
export function routeTitle(path: string): string {
  if (TITLE_MAP[path]) return TITLE_MAP[path]
  if (path.startsWith('/grading')) return '打分工作台'
  if (path.startsWith('/stats')) return '成绩统计'
  return '工作台'
}
