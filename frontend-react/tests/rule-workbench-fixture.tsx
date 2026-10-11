import { createRoot } from 'react-dom/client'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import RuleGroupWorkbench from '../src/pages/scheduling/RuleGroupWorkbench'
import '../src/index.css'
import '../src/pages/scheduling/index.css'
import type { Grade, SchedulingResources } from '../src/types'

const resources = {
  teachers: [{ id: 11, name: '王老师' }],
  subjects: [{ id: 1, name: '班会' }, { id: 2, name: '数学' }],
  classes: [{ id: 101, name: '高一（1）班', grade_id: 1, head_teacher_id: 11 }],
  assignments: [{id:1,class_id:101,subject_id:2,teacher_id:11,weekly_periods:5,academic_year:'2026-2027',term:'2'}], teacher_subject_ids: { '11': [2] },
} as SchedulingResources
const grades = [{ id: 1, name: '高一' }] as Grade[]
createRoot(document.getElementById('root')!).render(
  <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#098fce', borderRadius: 8, fontFamily: '"Microsoft YaHei", sans-serif' } }}>
    <App><RuleGroupWorkbench resources={resources} grades={grades} academicYear="2026-2027" term="2" /></App>
  </ConfigProvider>,
)
