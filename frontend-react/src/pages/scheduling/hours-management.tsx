import { useState } from 'react'
import { Segmented } from 'antd'
import type { ComponentProps } from 'react'
import CourseHoursPanel from './course-hours'
import WalkCourseHoursPanel from './walk-course-hours'

type HoursManagementProps = ComponentProps<typeof CourseHoursPanel> & {
  timetableMode: 'administrative' | 'walk_class'
}

export default function HoursManagement(props: HoursManagementProps) {
  const [mode, setMode] = useState('administrative')
  const modeSwitch = props.timetableMode === 'walk_class' && <Segmented size="large" value={mode} onChange={setMode} aria-label="课时管理类型"
      options={[{ label: '行政班课时', value: 'administrative' }, { label: '走班课时', value: 'walk' }]} />
  return <>
    {mode === 'administrative' ? <CourseHoursPanel {...props} toolbarLeading={modeSwitch} /> : <WalkCourseHoursPanel
      toolbarLeading={modeSwitch} academicYear={props.academicYear} term={props.term} subjects={props.subjects}
      initialGradeId={props.classes.find((item) => item.id === props.classId)?.grade_id} />}
  </>
}
