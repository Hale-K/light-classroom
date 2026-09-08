import { useEffect } from 'react'
import { createBrowserRouter, Navigate, Outlet, useNavigate } from 'react-router-dom'
import { setAuthResolver } from '@/api'
import { DEFAULT_SCHOOL_CODE } from '@/types'
import { useAdminStore } from '@/store/admin'
import { useAuthStore } from '@/store/auth'
import RequireAuth from './RequireAuth'
import MainLayout from '@/layouts/MainLayout'
import AdminLayout from '@/layouts/AdminLayout'
import Login from '@/pages/login'
import AdminLogin from '@/pages/admin/Login'
import AdminSchools from '@/pages/admin/Schools'
import Dashboard from '@/pages/dashboard'
import ExamManage from '@/pages/exam'
import ScanManage from '@/pages/scan'
import SchedulingView from '@/pages/scheduling'
import OnboardingView from '@/pages/onboarding'
import StudentsView from '@/pages/students'
import ClassesView from '@/pages/classes'
import PersonnelView from '@/pages/personnel'
import StaffPositionsView from '@/pages/staff-positions'
import RolesView from '@/pages/roles'
import PermissionsView from '@/pages/permissions'
import RbacWorkbenchView from '@/pages/rbac'
import GaokaoView from '@/pages/gaokao'
import SeatingView from '@/pages/seating'
import ExamSchedulingView from '@/pages/exam-scheduling'
import ExamRoomsView from '@/pages/exam-rooms'
import ExamVenuesView from '@/pages/exam-venues'
import ExamCalendarView from '@/pages/exam-calendar'
import ExamInvigilatorsView from '@/pages/exam-invigilators'
import SchoolSettingsView from '@/pages/settings'
import SubjectManagementView from '@/pages/subjects'
import SpaceResourcesView from '@/pages/space-resources'
import MeetingsView from '@/pages/meetings'
import GradingWorkbench from '@/pages/grading'
import StatsView from '@/pages/stats'
import TeacherProfilesView from '@/pages/teacher-profiles'
import FileCenterView from '@/pages/file-center'
import AiProvidersView from '@/pages/ai-providers'
import TeacherModulePlaceholder from '@/pages/dashboard/TeacherModulePlaceholder'
import TeacherCourses from '@/pages/dashboard/TeacherCourses'
import TeacherPreparation from '@/pages/teacher/TeacherPreparation'
import TeacherClasses from '@/pages/teacher/TeacherClasses'
import TeacherStudents from '@/pages/teacher/TeacherStudents'
import ForbiddenPage from '@/pages/Forbidden'
import TutorialPage from '@/pages/Tutorial'

/** 根路由：挂载 API 鉴权 resolver（token / 学校代码 / 401 跳转） */
function Root() {
  const navigate = useNavigate()
  useEffect(() => {
    const readSchoolCode = () => {
      const c = (localStorage.getItem('zh_school_code') || '').trim()
      // 归一化历史残留值（早期默认 'default' 与后端租户 'demo' 不一致）
      return !c || c === 'default' ? DEFAULT_SCHOOL_CODE : c
    }
    setAuthResolver({
      getToken: () => localStorage.getItem('zh_token'),
      getAdminToken: () => localStorage.getItem('zh_admin_token'),
      getSchoolCode: readSchoolCode,
      onUnauthorized: () => {
        const path = window.location.pathname
        if (path.startsWith('/admin')) {
          useAdminStore.getState().logout()
          navigate('/admin/login', { replace: true })
          return
        }
        useAuthStore.getState().logout()
        navigate('/login', { replace: true })
      },
      onForbidden: () => {
        const from = window.location.pathname + window.location.search
        navigate('/403', { replace: true, state: { from } })
      },
    })
  }, [navigate])
  return <Outlet />
}

export const router = createBrowserRouter([
  {
    element: <Root />,
    children: [
      { path: '/login', element: <Login /> },
      // 平台超管后台（创建学校）
      { path: '/admin/login', element: <AdminLogin /> },
      { path: '/403', element: <ForbiddenPage /> },
      { path: '/tutorial', element: <TutorialPage /> },
      {
        path: '/admin',
        element: (
          <RequireAuth admin>
            <AdminLayout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: <Navigate to="/admin/schools" replace /> },
          { path: 'schools', element: <AdminSchools /> },
        ],
      },
      {
        path: '/',
        element: (
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        ),
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: 'dashboard', element: <Dashboard /> },
          { path: 'exams', element: <ExamManage /> },
          { path: 'scans', element: <ScanManage /> },
          { path: 'scheduling', element: <SchedulingView /> },
          { path: 'teacher-courses', element: <TeacherCourses /> },
          { path: 'teacher-preparation', element: <TeacherPreparation /> },
          { path: 'teacher-classes', element: <TeacherClasses /> },
          { path: 'teacher-students', element: <TeacherStudents /> },
          { path: 'onboarding', element: <OnboardingView /> },
          { path: 'file-center', element: <FileCenterView /> },
          { path: 'ai-providers', element: <AiProvidersView /> },
          { path: 'students', element: <StudentsView /> },
          { path: 'classes', element: <ClassesView /> },
          { path: 'organization', element: <Navigate to="/staff?tab=organization" replace /> },
          { path: 'staff', element: <PersonnelView /> },
          { path: 'staff-positions', element: <StaffPositionsView /> },
          { path: 'rbac', element: <RbacWorkbenchView /> },
          { path: 'roles', element: <RolesView /> },
          { path: 'permissions', element: <PermissionsView /> },
          { path: 'gaokao', element: <GaokaoView /> },
          { path: 'seating', element: <SeatingView /> },
          { path: 'exam-scheduling', element: <ExamSchedulingView /> },
          { path: 'exam-rooms', element: <ExamRoomsView /> },
          { path: 'exam-venues', element: <ExamVenuesView /> },
          { path: 'exam-calendar', element: <ExamCalendarView /> },
          { path: 'exam-invigilators', element: <ExamInvigilatorsView /> },
          { path: 'settings', element: <SchoolSettingsView /> },
          { path: 'subjects', element: <SubjectManagementView /> },
          { path: 'campus-buildings', element: <SpaceResourcesView /> },
          { path: 'rooms', element: <Navigate to="/campus-buildings?tab=rooms" replace /> },
          { path: 'meetings', element: <MeetingsView /> },
          { path: 'grading/:paperId', element: <GradingWorkbench /> },
          { path: 'stats/:paperId', element: <StatsView /> },
          { path: 'teacher-profiles', element: <TeacherProfilesView /> },
          { path: 'teacher-grades', element: <TeacherModulePlaceholder icon="chart" title="成绩" description="成绩汇总功能正在接入，阅卷成绩仍可从作业与试卷页面查看。" /> },
          { path: 'teacher-notices', element: <TeacherModulePlaceholder icon="message" title="通知" description="当前暂无新的教学通知。" /> },
        ],
      },
    ],
  },
])
