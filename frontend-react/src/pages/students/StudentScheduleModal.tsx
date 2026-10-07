import { Alert, Button, Empty, Modal, Spin, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { gaokaoApi, schedulingApi } from '@/api'
import ScheduleGrid from '@/components/ScheduleGrid'
import type { Student } from '@/types'
import './student-schedule.css'

export default function StudentScheduleModal({ student, academicYear, term, onClose }: {
  student: Student; academicYear: string; term: string; onClose: () => void
}) {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ['student-timetable', student.id, student.class_id, student.grade_id, academicYear, term],
    staleTime: 0,
    queryFn: async () => {
      const scope = { academic_year: academicYear, term }
      const [entries, grid] = await Promise.all([
        gaokaoApi.studentTimetable(student.id, scope),
        schedulingApi.gridConfig({ ...scope, grade_id: student.grade_id ?? undefined }),
      ])
      return { entries, grid }
    },
    retry: false,
  })
  return (
    <Modal className="student-schedule-modal" title={`${student.name} · 个人课表`}
      open onCancel={onClose} footer={null} width={1280} centered>
      <div className="student-schedule-context">
        <span>{academicYear} · 第{term}学期</span>
        <Tag>{student.class_name || '未分行政班'}</Tag>
      </div>
      {isPending ? <div className="student-schedule-loading"><Spin tip="正在查询课表"><div /></Spin></div>
        : error ? <Alert type="error" showIcon message="课表查询失败"
          description={error instanceof Error ? error.message : '请重试'}
          action={<Button onClick={() => void refetch()}>重试</Button>} />
        : !data?.entries.length ? <Empty description="本学期暂无课表" />
        : <div className="student-schedule-grid">
          <ScheduleGrid entries={data.entries}
            periods={Math.max(data.grid.periods_per_day, ...data.entries.filter(e => !data.grid.enable_evening || e.period < (data.grid.evening_start_period ?? 13)).map(e => e.period))}
            days={Math.max(data.grid.days, ...data.entries.map(e => e.weekday))}
            dailyPeriods={data.grid.daily_periods}
            showEvening={data.grid.enable_evening && data.entries.some(e => e.period >= (data.grid.evening_start_period ?? 13))}
            eveningStartPeriod={data.grid.evening_start_period} showClassName showLessonDetails />
        </div>}
    </Modal>
  )
}
