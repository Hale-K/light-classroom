import { useEffect, useMemo, useState } from 'react'
import { App, Button, Checkbox, Input, Select, Spin, Table, Tag } from 'antd'
import { examApi, examSchedulingApi, orgApi } from '@/api'
import type { Exam, ExamRoomAssignment, ExamRoomEntry, ExamSchedulingConfig, Grade } from '@/types'
import PageHeader from '@/components/PageHeader'
import ExamModuleNav from '@/pages/exam-scheduling/ModuleNav'
import '@/pages/exam-scheduling/index.css'

const ROOM_TYPE_LABEL = { standard: '普通考场', special: '特殊考场', reserve: '备用考场' }
const EXAM_ROOM_STATE_LABEL: Record<string, string> = { available: '可用', selected: '已选用', scheduled: '已编排', ongoing: '考试中', completed: '已完成', maintenance: '维护中', disabled: '已停用' }

export default function ExamVenuesView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [exams, setExams] = useState<Exam[]>([])
  const [grades, setGrades] = useState<Grade[]>([])
  const [config, setConfig] = useState<ExamSchedulingConfig>()
  const [gradeIds, setGradeIds] = useState<number[]>([])
  const [examId, setExamId] = useState<number>()
  const [rooms, setRooms] = useState<ExamRoomEntry[]>([])
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [confirmed, setConfirmed] = useState(false)
  const [assignedRooms, setAssignedRooms] = useState<ExamRoomAssignment[]>([])
  const [keyword, setKeyword] = useState('')

  const loadSelection = async (id: number, catalog: ExamRoomEntry[]) => {
    setLoading(true)
    try {
      const [plan, scope, generatedPlan] = await Promise.all([examSchedulingApi.venues(id), examSchedulingApi.config(id), examSchedulingApi.plan(id)])
      setConfig(scope); setGradeIds(scope.grade_ids)
      setAssignedRooms(generatedPlan.rooms)
      const names = new Set(plan.rooms.map((room) => room.name))
      setSelectedIds(plan.confirmed ? catalog.filter((room) => names.has(room.name)).map((room) => room.id) : catalog.filter((room) => room.status === 'available').map((room) => room.id))
      setConfirmed(plan.confirmed)
    } catch (error) { message.error(error instanceof Error ? error.message : '考场安排加载失败') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    Promise.all([examApi.list(), examSchedulingApi.rooms({ page: 1, page_size: 300 }), orgApi.grades()]).then(([examRows, roomData, gradeRows]) => {
      setExams(examRows); setRooms(roomData.items); setGrades(gradeRows)
      if (examRows[0]) { setExamId(examRows[0].id); void loadSelection(examRows[0].id, roomData.items) }
    }).catch((error) => message.error(error instanceof Error ? error.message : '页面加载失败'))
  }, [])

  const selected = rooms.filter((room) => selectedIds.includes(room.id))
  const visible = useMemo(() => {
    const value = keyword.trim().toLowerCase()
    return value ? rooms.filter((room) => `${room.name} ${room.building || ''}`.toLowerCase().includes(value)) : rooms
  }, [keyword, rooms])
  const markChanged = (ids: number[]) => { setSelectedIds(ids); setConfirmed(false) }
  const examRoomState = (room: ExamRoomEntry) => {
    if (room.status !== 'available') return room.status
    const dates = assignedRooms.filter((item) => item.room_name === room.name).map((item) => item.exam_date).sort()
    const today = new Date().toISOString().slice(0, 10)
    if (dates.includes(today)) return 'ongoing'
    if (dates.length && dates[dates.length - 1] < today) return 'completed'
    if (dates.length) return 'scheduled'
    return selectedIds.includes(room.id) ? 'selected' : 'available'
  }

  const save = async () => {
    if (!examId || !selected.length) return message.warning('请至少选择一个考场')
    if (!gradeIds.length) return message.warning('请至少选择一个参考年级')
    setLoading(true)
    try {
      await Promise.all([
        examSchedulingApi.saveVenues(examId, selected.map((room) => ({ name: room.name, capacity: room.capacity, source_type: room.source_class_id ? 'classroom' : 'custom', source_class_id: room.source_class_id }))),
        examSchedulingApi.saveConfig(examId, { grade_ids: gradeIds, start_date: config?.start_date, excluded_dates: config?.excluded_dates || [], sessions: config?.sessions || [], invigilators_per_room: config?.invigilators_per_room || 1 }),
      ])
      setConfirmed(true); message.success(`已保存 ${selected.length} 间本次考试考场`)
    } catch (error) { message.error(error instanceof Error ? error.message : '考场安排保存失败') }
    finally { setLoading(false) }
  }

  const columns = [
    { title: '考场名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'room_type', width: 120, render: (value: ExamRoomEntry['room_type']) => ROOM_TYPE_LABEL[value] },
    { title: '位置 / 楼栋', dataIndex: 'building', render: (value?: string) => value || '未填写' },
    { title: '座位容量', dataIndex: 'capacity', width: 110 },
    { title: '资源状态', dataIndex: 'status', width: 100, render: (value: ExamRoomEntry['status']) => value === 'available' ? '可用' : value === 'maintenance' ? '维护中' : '已停用' },
    { title: '本次状态', width: 100, render: (_: unknown, room: ExamRoomEntry) => EXAM_ROOM_STATE_LABEL[examRoomState(room)] },
    { title: '来源', width: 120, render: (_: unknown, row: ExamRoomEntry) => row.source_class_id ? '行政班教室' : '手动创建' },
  ]

  return <Spin spinning={loading}><div className="es-page">
    <PageHeader title="考场安排" extra={<Button type="primary" onClick={save}>保存本次考场</Button>} />
    <p className="zh-page-desc">从学校考场资源中，确定本次考试实际启用哪些考场。</p>
    <ExamModuleNav />
    <section className="es-venue-picker">
      <header><div><span>本次考试范围</span><h2>选择考试与考场</h2><p>本页只确定场地范围，不设置日期，也不分配考生。</p></div><div className="es-venue-total"><strong>{selected.length}</strong><span>间已选</span><strong>{selected.reduce((sum, room) => sum + room.capacity, 0)}</strong><span>个座位</span><Tag color={confirmed ? 'success' : 'warning'}>{confirmed ? '已确认' : '待确认'}</Tag></div></header>
      <div className="es-venue-tools"><Select className="es-exam-select" value={examId} onChange={(id) => { setExamId(id); void loadSelection(id, rooms) }} options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /><Select mode="multiple" value={gradeIds} onChange={setGradeIds} placeholder="选择参考年级" options={grades.map((grade) => ({ label: grade.name, value: grade.id }))} /><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索考场" /><Checkbox checked={selectedIds.length === rooms.filter((room) => room.status === 'available').length && selectedIds.length > 0} onChange={(event) => markChanged(event.target.checked ? rooms.filter((room) => room.status === 'available').map((room) => room.id) : [])}>全选可用</Checkbox></div>
      <Table rowKey="id" columns={columns} dataSource={visible} rowSelection={{ selectedRowKeys: selectedIds, preserveSelectedRowKeys: true, getCheckboxProps: (room) => ({ disabled: room.status !== 'available' }), onChange: (keys) => markChanged(keys.map(Number)) }} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 间` }} />
    </section>
  </div></Spin>
}
