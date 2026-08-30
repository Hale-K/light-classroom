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
import StudentsView from '@/pages/students'
import ClassesView from '@/pages/classes'
import PersonnelView from '@/pages/personnel'
import StaffPositionsView from '@/pages/staff-positions'
import RolesView from '@/pages/roles'
import PermissionsView from '@/pages/permissions'
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
          { path: 'students', element: <StudentsView /> },
          { path: 'classes', element: <ClassesView /> },
          { path: 'organization', element: <Navigate to="/staff?tab=organization" replace /> },
          { path: 'staff', element: <PersonnelView /> },
          { path: 'staff-positions', element: <StaffPositionsView /> },
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
        ],
      },
    ],
  },
])
