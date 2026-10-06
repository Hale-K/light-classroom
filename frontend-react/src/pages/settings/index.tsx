import SchoolSettingsForm from '@/components/SchoolSettingsForm'
import GradeManagementPanel from './GradeManagementPanel'
import './index.css'

/** 系统设置页（入口：侧边栏左下角菜单 / 路由直达 /settings） */
export default function SchoolSettingsView() {
  return (
    <section className="stg-page-v2">
      <SchoolSettingsForm gradePanel={<GradeManagementPanel />} />
    </section>
  )
}
