import { useEffect, useState } from 'react'
import { Alert, App, Button, Dropdown, Modal, Select, Space, Spin, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { gaokaoApi } from '@/api'
import type { Grade } from '@/types'

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
    if (!gradeId) return
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
    if (!gradeId) return
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

  const rosterGroups = (() => {
    const map = new Map<string, RosterItem[]>()
    for (const item of rosterItems) {
      const key = item.class_name || '未分班'
      const bucket = map.get(key)
      if (bucket) bucket.push(item)
      else map.set(key, [item])
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0], 'zh'))
  })()

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
      render: (_, row) => <Button size="small" onClick={() => openRoster(row)}>查看班级</Button>,
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
          {jointSupported ? <Dropdown trigger={['click']} menu={{ items: [{ key: 'walk', label: '单独生成走班课表',
            disabled: !gradeId || loading || generating, onClick: confirmGenerate,
          }] }}><Button loading={generating}>高级操作</Button></Dropdown> : <Button type="primary" loading={generating} disabled={!gradeId || loading} onClick={confirmGenerate}>
            {rows.length ? '重新生成走班课表' : '生成走班课表'}
          </Button>}
        </Space>
      </div>
      <Alert
        type="info"
        showIcon
        message={`${academicYear} 学年 · 第 ${term} 学期`}
        description={jointSupported ? '使用页首“联合排课”同步分班和排课；高级操作仅重排走班课表，不调整行政课。' : '先保存行政班课表，再生成走班课表；走班单独保存，不修改行政课和规则。'}
        style={{ marginBottom: 16 }}
      />
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
      <Modal
        title={roster ? `学生构成 · ${roster.name}` : '学生构成'}
        open={Boolean(roster)}
        onCancel={() => setRoster(null)}
        footer={null}
        width={520}
      >
        {rosterLoading && <div style={{ textAlign: 'center', padding: '32px 0' }}><Spin tip="正在加载学生名单…" /></div>}
        {!rosterLoading && rosterError && <Alert type="error" showIcon message={rosterError} />}
        {!rosterLoading && !rosterError && (
          <>
            <div style={{ marginBottom: 12, color: 'var(--text-2)', fontSize: 13 }}>
              共 <strong style={{ color: 'var(--ink)' }}>{rosterItems.length}</strong> 人
              {rosterGroups.length > 0 && <> · 来自 {rosterGroups.length} 个行政班</>}
            </div>
            {rosterGroups.length === 0 && (
              <div style={{ color: 'var(--text-3)', padding: '12px 0' }}>该教学班暂无学生。</div>
            )}
            {rosterGroups.map(([className, members]) => (
              <div key={className} style={{ marginBottom: 14 }}>
                <div style={{ marginBottom: 4 }}>
                  <Tag color="blue">{className}</Tag>
                  <span style={{ color: 'var(--text-2)', fontSize: 12 }}>{members.length} 人</span>
                </div>
                <div style={{ color: 'var(--text-1)', fontSize: 13, lineHeight: 1.8 }}>
                  {members.map((item) => item.student_name).join('、')}
                </div>
              </div>
            ))}
          </>
        )}
      </Modal>
    </section>
  )
}
