import { useEffect, useState } from 'react'
import { App, Input, Select, Spin, Table, Tag } from 'antd'
import { examApi, examSchedulingApi } from '@/api'
import type { Exam, ExamCandidateAssignment, ExamPlan, ExamRoomAssignment } from '@/types'
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
  useEffect(() => { examApi.list().then((rows) => { setExams(rows); if (rows[0]) changeExam(rows[0].id) }) }, [])

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
    <PageHeader title="人员排考" />
    <p className="zh-page-desc">这里只查看考生、座位和监考教师的最终分配，不再设置考场与考试日期。</p>
    <ExamModuleNav />
    <section className="es-personnel">
      <header className="es-personnel-head"><div><span>人员分配结果</span><h2>考生与监考安排</h2></div><Select className="es-exam-select" value={examId} onChange={changeExam} options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /></header>
      <div className="es-kpis"><div><span>参考学生</span><strong>{plan.summary.student_count}</strong></div><div><span>考生场次</span><strong>{plan.summary.candidate_assignment_count}</strong></div><div><span>启用考场场次</span><strong>{plan.summary.room_count}</strong></div><div><span>监考教师</span><strong>{plan.summary.invigilator_count}</strong></div></div>
    </section>
    <section className="es-personnel"><header className="es-section-head"><div><h3>考场与监考</h3><span>每个考试场次的考场容量和监考教师</span></div></header><Table rowKey="id" columns={roomColumns} dataSource={plan.rooms} pagination={{ pageSize: 10, showSizeChanger: false }} /></section>
    <section className="es-personnel"><header className="es-section-head"><div><h3>考生座位明细</h3><span>按姓名、学号、年级、科目、日期或考场筛选</span></div></header><div className="es-filter-bar"><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={(value) => examId && loadCandidates(examId, 1, value)} placeholder="搜索姓名或学号" /><Select allowClear placeholder="全部年级" value={gradeId} onChange={(value) => { setGradeId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, value) }} options={[...new Map(plan.rooms.map((room) => [room.grade_id, { label: room.grade_name, value: room.grade_id }])).values()]} /><Select allowClear placeholder="全部科目" value={subjectId} onChange={(value) => { setSubjectId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, gradeId, value) }} options={[...new Map(plan.rooms.map((room) => [room.subject_id, { label: room.subject_name, value: room.subject_id }])).values()]} /><Select allowClear placeholder="全部日期" value={examDate} onChange={(value) => { setExamDate(value); if (examId) void loadCandidates(examId, 1, keyword, roomId, gradeId, subjectId, value) }} options={[...new Set(plan.rooms.map((room) => room.exam_date))].map((value) => ({ label: value, value }))} /><Select allowClear placeholder="全部考场" value={roomId} onChange={(value) => { setRoomId(value); if (examId) void loadCandidates(examId, 1, keyword, value) }} options={plan.rooms.map((room) => ({ label: `${room.exam_date} · ${room.room_name} · ${room.subject_name}`, value: room.id }))} /></div><Table rowKey="id" columns={candidateColumns} dataSource={candidates} pagination={{ current: page, pageSize: 10, total: candidateTotal, showSizeChanger: false, showTotal: (total) => `共 ${total} 条`, onChange: (next) => examId && loadCandidates(examId, next) }} /></section>
  </div></Spin>
}
