import { useEffect, useMemo, useState } from 'react'
import { App, Button, DatePicker, Form, Input, Modal, Select, Spin, Switch, Table, Tag } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { examApi, examSchedulingApi } from '@/api'
import type { Exam, ExamInvigilatorEntry, ExamPlan } from '@/types'
import PageHeader from '@/components/PageHeader'
import ExamModuleNav from '@/pages/exam-scheduling/ModuleNav'
import '@/pages/exam-scheduling/index.css'

const STATE_LABEL: Record<ExamInvigilatorEntry['state'], string> = { available: '可监考', assigned: '已分配', leave: '休假', excluded: '本次排除', disabled: '账号停用', conflict: '时间冲突' }
const STATE_COLOR: Record<ExamInvigilatorEntry['state'], string> = { available: 'success', assigned: 'processing', leave: 'warning', excluded: 'default', disabled: 'error', conflict: 'error' }
interface EditorValues { enabled: boolean; leave?: [Dayjs, Dayjs]; unavailable_slots?: string[]; note?: string }

export default function ExamInvigilatorsView() {
  const { message } = App.useApp()
  const [form] = Form.useForm<EditorValues>()
  const [loading, setLoading] = useState(false)
  const [exams, setExams] = useState<Exam[]>([])
  const [examId, setExamId] = useState<number>()
  const [teachers, setTeachers] = useState<ExamInvigilatorEntry[]>([])
  const [plan, setPlan] = useState<ExamPlan>()
  const [keyword, setKeyword] = useState('')
  const [stateFilter, setStateFilter] = useState<string>()
  const [editing, setEditing] = useState<ExamInvigilatorEntry>()

  const load = async (id: number) => {
    setLoading(true)
    try { const [rows, planData] = await Promise.all([examSchedulingApi.invigilators(id), examSchedulingApi.plan(id)]); setTeachers(rows); setPlan(planData) }
    catch (error) { message.error(error instanceof Error ? error.message : '监考教师加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { examApi.list().then((rows) => { setExams(rows); if (rows[0]) { setExamId(rows[0].id); void load(rows[0].id) } }) }, [])
  const slots = useMemo(() => [...new Map((plan?.schedules || []).map((item) => [`${item.exam_date}#${item.session_index}`, { value: `${item.exam_date}#${item.session_index}`, label: `${item.exam_date} ${item.start_time}—${item.end_time}` }])).values()], [plan])
  const filtered = useMemo(() => teachers.filter((teacher) => (!keyword.trim() || teacher.teacher_name.toLowerCase().includes(keyword.trim().toLowerCase())) && (!stateFilter || teacher.state === stateFilter)), [keyword, stateFilter, teachers])
  const open = (teacher: ExamInvigilatorEntry) => { setEditing(teacher); form.setFieldsValue({ enabled: teacher.enabled, leave: teacher.leave_start && teacher.leave_end ? [dayjs(teacher.leave_start), dayjs(teacher.leave_end)] : undefined, unavailable_slots: teacher.unavailable_slots, note: teacher.note || '' }) }
  const save = async () => {
    if (!examId || !editing) return
    const values = await form.validateFields(); setLoading(true)
    try { await examSchedulingApi.saveInvigilator(examId, editing.teacher_id, { enabled: values.enabled, leave_start: values.leave?.[0].format('YYYY-MM-DD') || null, leave_end: values.leave?.[1].format('YYYY-MM-DD') || null, unavailable_slots: values.unavailable_slots || [], note: values.note || null }); setEditing(undefined); await load(examId); message.success('教师监考状态已保存') }
    catch (error) { message.error(error instanceof Error ? error.message : '状态保存失败') }
    finally { setLoading(false) }
  }
  const columns = [
    { title: '教师', dataIndex: 'teacher_name' },
    { title: '账号', dataIndex: 'account_status', width: 100, render: (value: string) => value === 'active' ? '在职' : '停用' },
    { title: '本次状态', dataIndex: 'state', width: 120, render: (value: ExamInvigilatorEntry['state']) => <Tag color={STATE_COLOR[value]}>{STATE_LABEL[value]}</Tag> },
    { title: '休假日期', width: 190, render: (_: unknown, row: ExamInvigilatorEntry) => row.leave_start ? `${row.leave_start} 至 ${row.leave_end}` : '无' },
    { title: '不可用场次', dataIndex: 'unavailable_slots', width: 110, render: (value: string[]) => value.length },
    { title: '已监考', dataIndex: 'assigned_count', width: 90, render: (value: number) => `${value} 场` },
    { title: '操作', width: 90, render: (_: unknown, row: ExamInvigilatorEntry) => <Button type="link" disabled={row.account_status !== 'active'} onClick={() => open(row)}>设置</Button> },
  ]
  return <Spin spinning={loading}><div className="es-page">
    <PageHeader title="监考教师" />
    <p className="zh-page-desc">监考池使用全校在职教师；休假、停用、本次排除或指定场次不可用的教师不会被算法安排。</p>
    <ExamModuleNav />
    <section className="es-personnel"><header className="es-personnel-head"><div><span>教师可用性</span><h2>监考资源池</h2></div><Select className="es-exam-select" value={examId} onChange={(id) => { setExamId(id); void load(id) }} options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /></header>
      <div className="es-state-flow"><span>在职教师</span><i>→</i><span>排除休假与禁用</span><i>→</i><span>检查场次冲突</span><i>→</i><span>已分配</span></div>
      <div className="es-filter-bar"><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索教师姓名" /><Select allowClear value={stateFilter} onChange={setStateFilter} placeholder="全部状态" options={Object.entries(STATE_LABEL).map(([value, label]) => ({ value, label }))} /></div>
      <Table rowKey="teacher_id" columns={columns} dataSource={filtered} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 名` }} />
    </section>
    <Modal title={editing ? `设置 ${editing.teacher_name} 的监考状态` : '设置监考状态'} open={!!editing} onCancel={() => setEditing(undefined)} onOk={save} okText="保存" cancelText="取消" forceRender><Form form={form} layout="vertical"><Form.Item label="参与本次监考" name="enabled" valuePropName="checked"><Switch /></Form.Item><Form.Item label="休假日期" name="leave"><DatePicker.RangePicker /></Form.Item><Form.Item label="指定不可用场次" name="unavailable_slots"><Select mode="multiple" options={slots} placeholder="可多选" /></Form.Item><Form.Item label="备注" name="note"><Input.TextArea rows={3} maxLength={200} /></Form.Item></Form></Modal>
  </div></Spin>
}
