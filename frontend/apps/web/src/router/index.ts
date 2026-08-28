import type { RouteRecordRaw } from 'vue-router'
import { createRouter, createWebHistory } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  // 平台超管后台（创建学校）
  {
    path: '/admin/login',
    name: 'admin-login',
    component: () => import('@/views/admin/AdminLogin.vue'),
    meta: { public: true, admin: true, title: '平台管理登录' },
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { admin: true },
    children: [
      {
        path: 'schools',
        name: 'admin-schools',
        component: () => import('@/views/admin/AdminSchools.vue'),
        meta: { admin: true, title: '学校管理' },
      },
    ],
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台', icon: 'dashboard' },
      },
      {
        path: 'exams',
        name: 'exams',
        component: () => import('@/views/ExamManage.vue'),
        meta: { title: '考试与建卷', icon: 'file-text' },
      },
      {
        path: 'scans',
        name: 'scans',
        component: () => import('@/views/ScanManage.vue'),
        meta: { title: '扫描进卷', icon: 'scan' },
      },
      {
        path: 'scheduling',
        name: 'scheduling',
        component: () => import('@/views/SchedulingView.vue'),
        meta: { title: '排课管理', icon: 'calendar' },
      },
      {
        path: 'students',
        name: 'students',
        component: () => import('@/views/StudentsView.vue'),
        meta: { title: '学生档案', icon: 'users' },
      },
      {
        path: 'classes',
        name: 'classes',
        component: () => import('@/views/ClassesView.vue'),
        meta: { title: '行政班管理', icon: 'grid' },
      },
      {
        path: 'staff',
        name: 'staff',
        component: () => import('@/views/StaffView.vue'),
        meta: { title: '人员与权限', icon: 'users' },
      },
      {
        path: 'gaokao',
        name: 'gaokao',
        component: () => import('@/views/GaokaoView.vue'),
        meta: { title: '选科管理', icon: 'users' },
      },
      {
        path: 'seating',
        name: 'seating',
        component: () => import('@/views/SeatingView.vue'),
        meta: { title: '班级排座', icon: 'grid' },
      },
      {
        path: 'exam-scheduling',
        name: 'exam-scheduling',
        component: () => import('@/views/ExamSchedulingView.vue'),
        meta: { title: '排考管理', icon: 'clipboard' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SchoolSettingsView.vue'),
        meta: { title: '系统设置', icon: 'settings' },
      },
      {
        path: 'grading/:paperId(\\d+)',
        name: 'grading',
        component: () => import('@/views/GradingWorkbench.vue'),
        meta: { title: '打分工作台', icon: 'keyboard', fullscreen: true },
      },
      {
        path: 'stats/:paperId(\\d+)',
        name: 'stats',
        component: () => import('@/views/StatsView.vue'),
        meta: { title: '成绩统计', icon: 'chart' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const token = localStorage.getItem('zh_token')
  const adminToken = localStorage.getItem('zh_admin_token')
  // 平台超管后台：走独立 admin 令牌
  if (to.meta.admin) {
    if (to.name === 'admin-login') {
      return adminToken ? { path: '/admin/schools' } : true
    }
    return adminToken ? true : { path: '/admin/login', query: { redirect: to.fullPath } }
  }
  if (!to.meta.public && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && token) {
    return { path: '/' }
  }
  return true
})

export default router
