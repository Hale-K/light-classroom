import { useEffect, useState } from 'react'
import { Alert, App, Button, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { gaokaoApi } from '@/api'
import type { Grade } from '@/types'
import WalkRosterModal from './WalkRosterModal'

type WalkScheduleRow = Awaited<ReturnType<typeof gaokaoApi.schedules>>[number]
type TeachingClassRoster = Awaited<ReturnType<typeof gaokaoApi.teachingClassRoster>>
type RosterItem = TeachingClassRoster['items'][number]

const WEEKDAYS = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function WalkSchedulePanel({
  academicYear,
  term,
  grades,
  initialGradeId,
  jointSupported = false,
  onGradeChange,
}: {
  academicYear: string
  term: string
  grades: Grade[]
  initialGradeId?: number
  jointSupported?: boolean
  onGradeChange?: (gradeId: number) => void
}) {
  const { message, modal } = App.useApp()
  const [gradeId, setGradeId] = useState<number | undefined>(initialGradeId)
  const [rows, setRows] = useState<WalkScheduleRow[]>([])
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [generationError, setGenerationError] = useState('')
  // 「查看班级」弹窗：教学班成员按行政班分组
  const [roster, setRoster] = useState<{ id: number; name: string } | null>(null)
  const [rosterLoading, setRosterLoading] = useState(false)
  const [rosterError, setRosterError] = useState('')
  const [rosterItems, setRosterItems] = useState<RosterItem[]>([])

  useEffect(() => {
    setGradeId((current) =>
      grades.some((grade) => grade.id === initialGradeId)
        ? initialGradeId
        : grades.some((grade) => grade.id === current)
          ? current
          : grades[0]?.id,
    )
  }, [grades, initialGradeId])

  useEffect(() => {
    setGenerationError('')
  }, [gradeId, academicYear, term])

  useEffect(() => {
    let active = true
    if (!gradeId) {
      setRows([])
      return
    }
    setLoading(true)
    setLoadError('')
    gaokaoApi.schedules({ academic_year: academicYear, term, grade_id: gradeId })
      .then((data) => { if (active) setRows(data) })
      .catch((cause) => { if (active) setLoadError(cause instanceof Error ? cause.message : '走班课表加载失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [gradeId, academicYear, term])

  const generate = async () => {
    if (jointSupported || !gradeId) return
    setGenerating(true)
    setGenerationError('')
    try {
      const result = await gaokaoApi.generateSchedule({ grade_id: gradeId, academic_year: academicYear, term })
      const data = await gaokaoApi.schedules({ academic_year: academicYear, term, grade_id: gradeId })
      setRows(data)
      setLoadError('')
      message.success(`已生成 ${result.created} 个走班课位，涉及 ${result.teaching_class_count} 个教学班`)
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : '走班课表生成失败'
      setGenerationError(detail)
      message.error(detail)
    } finally {
      setGenerating(false)
    }
  }

  const confirmGenerate = () => {
    if (jointSupported || !gradeId) return
    if (rows.length) {
      modal.confirm({
        title: '重新生成走班课表？',
        content: '只会替换当前年级、当前学期的走班课表；行政班课表和排课规则不会被修改。',
        okText: '重新生成',
        cancelText: '取消',
        onOk: generate,
      })
      return
    }
    void generate()
  }

  const confirmClear = () => {
    if (!gradeId || rows.length === 0 || clearing) return
    const gradeName = grades.find((grade) => grade.id === gradeId)?.name ?? '当前年级'
    modal.confirm({
      title: '清空走班课表？',
      content: `清空${gradeName}当前列表中的 ${rows.length} 节走班课位。行政班课表、课时和任课关系不变。`,
      okText: '清空课表',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setClearing(true)
        try {
          const result = await gaokaoApi.clearSchedules({ grade_id: gradeId, academic_year: academicYear, term })
          const data = await gaokaoApi.schedules({ academic_year: academicYear, term, grade_id: gradeId })
          setRows(data)
          setLoadError('')
          message.success(`已清空 ${result.cleared} 节走班课位，可修改任课关系`)
        } catch (cause) {
          message.error(cause instanceof Error ? cause.message : '清空失败，请重试')
        } finally {
          setClearing(false)
        }
      },
    })
  }

  const openRoster = (row: WalkScheduleRow) => {
    setRoster({ id: row.teaching_class_id, name: row.teaching_class_name })
    setRosterLoading(true)
    setRosterError('')
    setRosterItems([])
    gaokaoApi.teachingClassRoster(row.teaching_class_id, { academic_year: academicYear, term })
      .then((data) => setRosterItems(data.items))
      .catch((cause) => setRosterError(cause instanceof Error ? cause.message : '学生名单加载失败'))
      .finally(() => setRosterLoading(false))
  }

  const columns: ColumnsType<WalkScheduleRow> = [
    { title: '星期', dataIndex: 'weekday', width: 100, render: (day: number) => WEEKDAYS[day] || `周${day}` },
    { title: '节次', dataIndex: 'period', width: 90, render: (period: number) => `第 ${period} 节`, sorter: (a, b) => a.period - b.period },
    { title: '科目', dataIndex: 'subject_name', width: 120, render: (name: string) => <Tag color="blue">{name}</Tag> },
    { title: '教学班', dataIndex: 'teaching_class_name', width: 180 },
    { title: '任课教师', dataIndex: 'teacher_name', width: 140, render: (name: string) => name || '未安排' },
    { title: '教室', dataIndex: 'room', width: 160, render: (room: string | null) => room || '未安排' },
    {
      title: '操作',
      key: 'roster',
      width: 110,
      render: (_, row) => <Button size="small" onClick={() => openRoster(row)}>学生名单</Button>,
    },
  ]

  return (
    <section className="sk-surface">
      <div className="sk-surface-head">
        <h2>走班课表</h2>
        <Space wrap>
          <Select
            aria-label="走班课表年级"
            value={gradeId}
            placeholder="选择年级"
            style={{ width: 180 }}
            options={grades.map((grade) => ({ value: grade.id, label: grade.name }))}
            onChange={(value) => { setGradeId(value); onGradeChange?.(value) }}
          />
          {!jointSupported && <Button type="primary" loading={generating} disabled={!gradeId || loading} onClick={confirmGenerate}>
            {rows.length ? '重新生成走班课表' : '生成走班课表'}
          </Button>}
          <Button danger disabled={!gradeId || loading || generating || clearing || rows.length === 0}
            loading={clearing} onClick={confirmClear}>清空走班课表</Button>
        </Space>
      </div>
      {generationError && <Alert type="error" showIcon message={generationError} style={{ marginBottom: 16 }} />}
      {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 16 }} />}
      <Table<WalkScheduleRow>
        rowKey="id"
        loading={loading || generating}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 950 }}
        pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 节` }}
        locale={{ emptyText: loadError ? '课表加载失败，请重试' : '当前年级本学期尚无走班课表' }}
      />
      {roster && <WalkRosterModal key={roster.id} name={roster.name} items={rosterItems}
        loading={rosterLoading} error={rosterError} onClose={() => setRoster(null)} />}
    </section>
  )
}
