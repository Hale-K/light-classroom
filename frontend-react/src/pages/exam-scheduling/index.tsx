import { useEffect, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Spin, Table, Tag } from 'antd'
import { examApi, examSchedulingApi } from '@/api'
import type { Exam, ExamCandidateAssignment, ExamPlan, ExamRoomAssignment } from '@/types'
import { EXAM_TYPE_DICT } from '@/types/dict'
import PageHeader from '@/components/PageHeader'
import ExamModuleNav from './ModuleNav'
import './index.css'

const EMPTY_PLAN: ExamPlan = { mode: '', schedules: [], rooms: [], summary: { day_count: 0, session_count: 0, room_count: 0, student_count: 0, candidate_assignment_count: 0, invigilator_count: 0 } }

export default function ExamSchedulingView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [exams, setExams] = useState<Exam[]>([])
  const [examId, setExamId] = useState<number>()
  const [plan, setPlan] = useState<ExamPlan>(EMPTY_PLAN)
  const [candidates, setCandidates] = useState<ExamCandidateAssignment[]>([])
  const [candidateTotal, setCandidateTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [roomId, setRoomId] = useState<number>()
  const [gradeId, setGradeId] = useState<number>()
  const [subjectId, setSubjectId] = useState<number>()
  const [examDate, setExamDate] = useState<string>()
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newExam, setNewExam] = useState({ name: '', exam_type: 'monthly', academic_year: `${new Date().getFullYear()}-${new Date().getFullYear() + 1}`, term: '1' })

  const loadPlan = async (id: number) => {
    setLoading(true)
    try { setPlan(await examSchedulingApi.plan(id)) }
    catch (error) { message.error(error instanceof Error ? error.message : '人员排考方案加载失败') }
    finally { setLoading(false) }
  }
  const loadCandidates = async (id: number, nextPage = 1, search = keyword, room = roomId, grade = gradeId, subject = subjectId, date = examDate) => {
    setLoading(true)
    try { const data = await examSchedulingApi.candidates(id, { page: nextPage, page_size: 10, keyword: search || undefined, room_assignment_id: room, grade_id: grade, subject_id: subject, exam_date: date }); setCandidates(data.items); setCandidateTotal(data.pagination.total); setPage(nextPage) }
    catch (error) { message.error(error instanceof Error ? error.message : '考生安排加载失败') }
    finally { setLoading(false) }
  }
  const changeExam = (id: number) => { setExamId(id); setRoomId(undefined); setGradeId(undefined); setSubjectId(undefined); setExamDate(undefined); setKeyword(''); void Promise.all([loadPlan(id), loadCandidates(id, 1, '', undefined, undefined, undefined, undefined)]) }
  const createExam = async () => {
    if (!newExam.name.trim()) return
    setCreating(true)
    try {
      const created = await examApi.create({ ...newExam, name: newExam.name.trim() })
      setExams((rows) => [created, ...rows])
      setCreateOpen(false)
      changeExam(created.id)
      message.success('考试已创建')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '考试创建失败')
    } finally {
      setCreating(false)
    }
  }
  useEffect(() => {
    examApi.list().then((rows) => { setExams(rows); if (rows[0]) changeExam(rows[0].id) })
      .catch((error) => message.error(error instanceof Error ? error.message : '考试列表加载失败'))
  }, [])

  const roomColumns = [
    { title: '日期', dataIndex: 'exam_date', width: 110 },
    { title: '科目', dataIndex: 'subject_name', width: 100 },
    { title: '年级', dataIndex: 'grade_name', width: 100 },
    { title: '考场', dataIndex: 'room_name' },
    { title: '考生', dataIndex: 'candidate_count', width: 90, render: (value: number, row: ExamRoomAssignment) => `${value} / ${row.capacity}` },
    { title: '监考教师', dataIndex: 'invigilator_names', render: (value: string[]) => value?.join('、') || '待安排' },
  ]
  const candidateColumns = [
    { title: '准考信息', render: (_: unknown, row: ExamCandidateAssignment) => <div className="es-person"><strong>{row.student_name}</strong><span>{row.student_no || '暂无学号'}</span></div> },
    { title: '科目', dataIndex: 'subject_name', width: 100 },
    { title: '考试日期', dataIndex: 'exam_date', width: 120 },
    { title: '时间', width: 130, render: (_: unknown, row: ExamCandidateAssignment) => `${row.start_time}—${row.end_time}` },
    { title: '考场', dataIndex: 'room_name' },
    { title: '座位号', dataIndex: 'seat_no', width: 90, render: (value: number) => <Tag>{String(value).padStart(2, '0')}</Tag> },
  ]

  return <Spin spinning={loading}><div className="es-page">
    <PageHeader title="排考管理" extra={<Button type="primary" onClick={() => setCreateOpen(true)}>新建考试</Button>} />
    <p className="zh-page-desc">创建考试后，设置考场范围、考试日程和监考教师，再生成考生安排。</p>
    <ExamModuleNav />
    <section className="es-personnel">
      <header className="es-personnel-head"><div><span>人员分配结果</span><h2>考生与监考安排</h2></div><Select className="es-exam-select" value={examId} onChange={changeExam} options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /></header>
      <div className="es-kpis"><div><span>参考学生</span><strong>{plan.summary.student_count}</strong></div><div><span>考生场次</span><strong>{plan.summary.candidate_assignment_count}</strong></div><div><span>启用考场场次</span><strong>{plan.summary.room_count}</strong></div><div><span>监考教师</span><strong>{plan.summary.invigilator_count}</strong></div></div>
    </section>
    <section className="es-personnel"><header className="es-section-head"><div><h3>考场与监考</h3><span>每个考试场次的考场容量和监考教师</span></div></header><Table rowKey="id" columns={roomColumns} dataSource={plan.rooms} pagination={{ pageSize: 10, showSizeChanger: false }} /></section>
    <section className="es-personnel"><header className="es-section-head"><div><h3>考生座位明细</h3><span>按姓名、学号、年级、科目、日期或考场筛选</span></div></header><div className="es-filter-bar"><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={(value) => examId && loadCandidates(examId, 1, value)} placeholder="搜索姓名或学号" /><Select allowClear placeholder="全部年级" value={gradeId} onChange={(value) => { setGradeId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, value) }} options={[...new Map(plan.rooms.map((room) => [room.grade_id, { label: room.grade_name, value: room.grade_id }])).values()]} /><Select allowClear placeholder="全部科目" value={subjectId} onChange={(value) => { setSubjectId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, gradeId, value) }} options={[...new Map(plan.rooms.map((room) => [room.subject_id, { label: room.subject_name, value: room.subject_id }])).values()]} /><Select allowClear placeholder="全部日期" value={examDate} onChange={(value) => { setExamDate(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, gradeId, subjectId, value) }} options={[...new Set(plan.rooms.map((room) => room.exam_date))].map((value) => ({ label: value, value }))} /><Select allowClear placeholder="全部考场" value={roomId} onChange={(value) => { setRoomId(value); if (examId) void loadCandidates(examId, 1, keyword, value) }} options={plan.rooms.map((room) => ({ label: `${room.exam_date} · ${room.room_name} · ${room.subject_name}`, value: room.id }))} /></div><Table rowKey="id" columns={candidateColumns} dataSource={candidates} pagination={{ current: page, pageSize: 10, total: candidateTotal, showSizeChanger: false, showTotal: (total) => `共 ${total} 条`, onChange: (next) => examId && loadCandidates(examId, next) }} /></section>
    <Modal title="新建考试" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={createExam} okText="创建" cancelText="取消" confirmLoading={creating} okButtonProps={{ disabled: !newExam.name.trim() }}>
      <Form layout="vertical">
        <Form.Item label="考试名称" required><Input autoFocus maxLength={100} value={newExam.name} onChange={(event) => setNewExam((value) => ({ ...value, name: event.target.value }))} placeholder="如：高一上学期期中考试" /></Form.Item>
        <Form.Item label="考试类型"><Select value={newExam.exam_type} onChange={(exam_type) => setNewExam((value) => ({ ...value, exam_type }))} options={Object.entries(EXAM_TYPE_DICT).map(([value, item]) => ({ value, label: item.label }))} /></Form.Item>
        <Form.Item label="学年"><Input maxLength={20} value={newExam.academic_year} onChange={(event) => setNewExam((value) => ({ ...value, academic_year: event.target.value }))} /></Form.Item>
        <Form.Item label="学期"><Select value={newExam.term} onChange={(term) => setNewExam((value) => ({ ...value, term }))} options={[{ value: '1', label: '第一学期' }, { value: '2', label: '第二学期' }]} /></Form.Item>
      </Form>
    </Modal>
  </div></Spin>
}
