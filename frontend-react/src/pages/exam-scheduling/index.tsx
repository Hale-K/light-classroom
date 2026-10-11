import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Empty, Form, Input, Modal, Select, Space, Spin, Table, Tabs, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { examApi, examSchedulingApi } from '@/api'
import type { Exam, ExamCandidateAssignment, ExamCheckReport, ExamPlan, ExamRoomAssignment } from '@/types'
import { EXAM_TYPE_DICT } from '@/types/dict'
import PageHeader from '@/components/PageHeader'
import './index.css'
import ExamSetup from './ExamSetup'
import ArrangementEditor from './ArrangementEditor'
import AdmissionTickets from './AdmissionTickets'
import PlanningOverview from './PlanningOverview'
import { TeacherDutyWorkspace, RoomDutyWorkspace } from './DutyWorkspace'
import { DutyDocument, ResourceDocument, printExamDocument } from './print'

const EMPTY_PLAN: ExamPlan = { mode: '', schedules: [], rooms: [], summary: { day_count: 0, session_count: 0, room_count: 0, student_count: 0, candidate_assignment_count: 0, invigilator_count: 0 } }

export default function ExamSchedulingView() {
  const { message } = App.useApp()
  const [params, setParams] = useSearchParams()
  const [setup, setSetup] = useState(false)
  const [setupTab, setSetupTab] = useState('calendar')
  const [setupFocus, setSetupFocus] = useState<'rooms' | 'staff'>()
  const [workspace, setWorkspace] = useState(['overview', 'settings', 'rooms', 'teachers', 'seats', 'printing'].includes(params.get('view') || '') ? params.get('view')! : 'overview')
  const switchWorkspace = (view: string) => { setWorkspace(view); setParams({ ...(examId ? { examId: String(examId) } : {}), view }, { replace: true }) }
  const [overviewRevision, setOverviewRevision] = useState(0)
  const prepare = (tab = 'calendar', focus?: 'rooms' | 'staff') => { setSetupTab(tab); setSetupFocus(focus); setSetup(true) }
  const [tickets, setTickets] = useState(false)
  const [editingRoom, setEditingRoom] = useState<ExamRoomAssignment>()
  const [editingTeacherId, setEditingTeacherId] = useState<number>()
  const [editingSwap, setEditingSwap] = useState(false)
  const [editingCandidate, setEditingCandidate] = useState<ExamCandidateAssignment>()
  const [check, setCheck] = useState<ExamCheckReport>()
  const [checking, setChecking] = useState(false)
  const selectedExam = useRef<number | undefined>(undefined)
  const [planLoading, setPlanLoading] = useState(false)
  const [candidatesLoading, setCandidatesLoading] = useState(false)
  const planRequest = useRef(0)
  const candidatesRequest = useRef(0)
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
  const readOnly = ['finished', 'archived'].includes(exams.find(e => e.id === examId)?.status || '')

  const loadPlan = async (id: number) => {
    const requestId = ++planRequest.current
    setPlanLoading(true)
    try {
      const data = await examSchedulingApi.plan(id)
      if (requestId === planRequest.current) setPlan(data)
    } catch (error) {
      if (requestId === planRequest.current) message.error(error instanceof Error ? error.message : '人员排考方案加载失败')
    } finally {
      if (requestId === planRequest.current) setPlanLoading(false)
    }
  }
  const loadCandidates = async (id: number, nextPage = 1, search = keyword, room: number | null = roomId ?? null, grade: number | null = gradeId ?? null, subject: number | null = subjectId ?? null, date: string | null = examDate ?? null) => {
    const requestId = ++candidatesRequest.current
    setCandidatesLoading(true)
    try {
      const data = await examSchedulingApi.candidates(id, { page: nextPage, page_size: 10, keyword: search || undefined, room_assignment_id: room ?? undefined, grade_id: grade ?? undefined, subject_id: subject ?? undefined, exam_date: date ?? undefined })
      if (requestId === candidatesRequest.current) {
        setCandidates(data.items)
        setCandidateTotal(data.pagination.total)
        setPage(nextPage)
      }
    } catch (error) {
      if (requestId === candidatesRequest.current) message.error(error instanceof Error ? error.message : '考生安排加载失败')
    } finally {
      if (requestId === candidatesRequest.current) setCandidatesLoading(false)
    }
  }
  const changeExam = (id: number) => {
    selectedExam.current = id
    setParams({ examId: String(id), view: workspace }, { replace: true })
    setSetup(false); setTickets(false); setEditingRoom(undefined); setEditingCandidate(undefined); setCheck(undefined)
    setEditingTeacherId(undefined); setEditingSwap(false)
    setExamId(id)
    setPlan(EMPTY_PLAN)
    setCandidates([])
    setCandidateTotal(0)
    setPage(1)
    setRoomId(undefined)
    setGradeId(undefined)
    setSubjectId(undefined)
    setExamDate(undefined)
    setKeyword('')
    void Promise.all([loadPlan(id), loadCandidates(id, 1, '', null, null, null, null)])
  }
  const createExam = async () => {
    if (!newExam.name.trim()) return
    setCreating(true)
    try {
      const created = await examApi.create({ ...newExam, name: newExam.name.trim() })
      setExams((rows) => [created, ...rows])
      setCreateOpen(false)
      changeExam(created.id)
      setWorkspace('settings')
      setParams({ examId: String(created.id), view: 'settings' }, { replace: true })
      prepare()
      message.success('考试已创建')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '考试创建失败')
    } finally {
      setCreating(false)
    }
  }
  useEffect(() => {
    let active = true
    examApi.list().then((rows) => { if (active) { setExams(rows); const initial = rows.find(r => r.id === Number(params.get('examId'))) || rows[0]; if (initial) changeExam(initial.id) } })
      .catch((error) => message.error(error instanceof Error ? error.message : '考试列表加载失败'))
    return () => { active = false; planRequest.current += 1; candidatesRequest.current += 1 }
  }, [])

  const refresh = () => { setCheck(undefined); if (examId) { void loadPlan(examId); void loadCandidates(examId) } }
  const checkPlan = async () => {
    if (!examId) return
    const target = examId
    setChecking(true)
    try { const report = await examSchedulingApi.checks(target); if (selectedExam.current === target) setCheck(report) }
    catch (e) { message.error(e instanceof Error ? e.message : '检查失败') }
    finally { setChecking(false) }
  }
  const printReport = async (type: 'duty' | 'resources') => {
    if (!examId) return
    setChecking(true)
    try {
      const report = await examSchedulingApi.checks(examId)
      setCheck(report)
      if (!report.ok) return
      const current = await examSchedulingApi.plan(examId)
      const title = exams.find(e => e.id === examId)?.name || '考试'
      await printExamDocument(title, type === 'duty' ? <DutyDocument exam={title} rooms={current.rooms} /> : <ResourceDocument exam={title} rooms={current.rooms} />)
    } catch (e) { message.error(e instanceof Error ? e.message : '打印失败') }
    finally { setChecking(false) }
  }
  const workloads = [...new Map(plan.rooms.flatMap(r => r.invigilator_ids.map((id, i) => [id, r.invigilator_names[i]] as const))).entries()].map(([id, name]) => {
    const assigned = plan.rooms.filter(r => r.invigilator_ids.includes(id))
    const minutes = assigned.reduce((n, r) => {
      const time = (v: string) => Number(v.slice(0, 2)) * 60 + Number(v.slice(3))
      return n + (r.start_time && r.end_time ? time(r.end_time) - time(r.start_time) : 0)
    }, 0)
    return { id, name, sessions: assigned.length, hours: (minutes / 60).toFixed(1), rooms: assigned }
  }).sort((a, b) => b.sessions - a.sessions)

  const renderIssue = (issue: ExamCheckReport['issues'][number], i: number) => <div key={i}><strong>{issue.message}</strong><span>{issue.suggestion}</span>{issue.room_assignment_id ? <Button type="link" disabled={readOnly} onClick={() => setEditingRoom(plan.rooms.find(r => r.id === issue.room_assignment_id))}>调整此考场</Button> : <Button type="link" disabled={readOnly} onClick={() => prepare(issue.code === 'calendar_rule' ? 'rules' : 'calendar')}>修改配置</Button>}</div>
  const candidateColumns = [
    { title: '准考信息', render: (_: unknown, row: ExamCandidateAssignment) => <div className="es-person"><strong>{row.student_name}</strong><span>{row.student_no || '暂无学号'}</span></div> },
    { title: '科目', dataIndex: 'subject_name', width: 100 },
    { title: '考试日期', dataIndex: 'exam_date', width: 120 },
    { title: '时间', width: 130, render: (_: unknown, row: ExamCandidateAssignment) => `${row.start_time}—${row.end_time}` },
    { title: '考场', dataIndex: 'room_name' },
    { title: '座位号', dataIndex: 'seat_no', width: 90, render: (value: number) => <Tag>{String(value).padStart(2, '0')}</Tag> },
    { title: '操作', width: 85, render: (_: unknown, r: ExamCandidateAssignment) => <Button type="link" disabled={readOnly} onClick={() => setEditingCandidate(r)}>调座位</Button> },
  ]

  const seatSection = <section className="es-personnel"><header className="es-section-head"><div><h3>考生座位明细</h3><span>按姓名、学号、年级、科目、日期或考场筛选</span></div></header><div className="es-filter-bar"><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={(value) => examId && loadCandidates(examId, 1, value)} placeholder="搜索姓名或学号" /><Select allowClear placeholder="全部年级" value={gradeId} onChange={(value) => { setGradeId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId ?? null, value ?? null) }} options={[...new Map(plan.rooms.map((room) => [room.grade_id, { label: room.grade_name, value: room.grade_id }])).values()]} /><Select allowClear placeholder="全部科目" value={subjectId} onChange={(value) => { setSubjectId(value); if (examId) void loadCandidates(examId, 1, keyword, roomId ?? null, gradeId ?? null, value ?? null) }} options={[...new Map(plan.rooms.map((room) => [room.subject_id, { label: room.subject_name, value: room.subject_id }])).values()]} /><Select allowClear placeholder="全部日期" value={examDate} onChange={(value) => { setExamDate(value); if (examId) void loadCandidates(examId, 1, keyword, roomId ?? null, gradeId ?? null, subjectId ?? null, value ?? null) }} options={[...new Set(plan.rooms.map((room) => room.exam_date))].map((value) => ({ label: value, value }))} /><Select allowClear placeholder="全部考场" value={roomId} onChange={(value) => { setRoomId(value); if (examId) void loadCandidates(examId, 1, keyword, value ?? null) }} options={plan.rooms.map((room) => ({ label: `${room.exam_date} · ${room.room_name} · ${room.subject_name}`, value: room.id }))} /></div><Table rowKey="id" columns={candidateColumns} dataSource={candidates} scroll={{ x: 800 }} pagination={{ current: page, pageSize: 10, total: candidateTotal, showSizeChanger: false, showTotal: (total) => `共 ${total} 条`, onChange: (next) => examId && loadCandidates(examId, next) }} /></section>

  return <Spin spinning={planLoading || candidatesLoading}><div className="es-page">
    <PageHeader title="排考管理" extra={<Button type="primary" onClick={() => setCreateOpen(true)}>新建考试</Button>} />
    <p className="zh-page-desc">设置规则，统筹日程、人员与考场，检查后打印考试材料。</p>
    <section className="es-personnel es-exam-context">
      <header className="es-personnel-head"><div><span>当前考试</span><h2>{exams.find(exam => exam.id === examId)?.name || '请选择考试'}</h2></div><Select aria-label="当前考试" className="es-exam-select" value={examId} onChange={changeExam} disabled={!exams.length || checking} placeholder="请选择考试" options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /></header>
    </section>
    {!exams.length && <section className="es-personnel"><Empty description="还没有考试，先新建一场考试" /></section>}
    {examId && <Tabs className="es-workspace-tabs" activeKey={workspace} onChange={switchWorkspace} items={[
      { key: 'overview', label: '数据总览', children: <>
        <section className="es-personnel"><div className="es-kpis"><div><span>参考学生</span><strong>{plan.summary.student_count}</strong></div><div><span>考生场次</span><strong>{plan.summary.candidate_assignment_count}</strong></div><div><span>考场使用次数</span><strong>{plan.summary.room_count}</strong></div><div><span>监考教师</span><strong>{plan.summary.invigilator_count}</strong></div></div></section>
        <PlanningOverview examId={examId} plan={plan} revision={overviewRevision} readOnly={readOnly} onAdjust={(_, kind) => switchWorkspace(kind === 'teacher' ? 'teachers' : 'rooms')} onPrepare={() => switchWorkspace('settings')} />
      </> },
      { key: 'settings', label: '考试设置', children: <section className="es-personnel">
        <header className="es-section-head"><div><h3>考试日程与规则</h3><span>{plan.rooms.length ? '安排已生成，可修改配置后重新生成' : '设置参考范围、科目和日程，再检查生成'}</span></div><Space wrap><Button disabled={readOnly} onClick={() => prepare('rules')}>排考规则</Button><Button type="primary" disabled={readOnly} onClick={() => prepare()}>{plan.rooms.length ? '修改排考配置' : '开始准备'}</Button><Button disabled={!plan.rooms.length} loading={checking} onClick={checkPlan}>检查冲突</Button></Space></header>
        {check && <Alert className="es-check-report" type={check.ok ? 'success' : 'error'} showIcon message={check.ok ? '检查通过，人员、考场和座位未发现冲突' : `发现 ${check.issues.length} 项待处理问题`} description={!check.ok && <div className="es-issues">{check.issues.slice(0, 3).map(renderIssue)}{check.issues.length > 3 && <details><summary>展开其余 {check.issues.length - 3} 项问题</summary>{check.issues.slice(3).map(renderIssue)}</details>}</div>} />}
        <Table rowKey="id" dataSource={plan.schedules} columns={[{ title: '日期', dataIndex: 'exam_date' }, { title: '时间', render: (_, row) => `${row.start_time}–${row.end_time}` }, { title: '年级', dataIndex: 'grade_name' }, { title: '科目', dataIndex: 'subject_name' }]} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 540 }} locale={{ emptyText: '设置并生成后显示考试日程' }} />
      </section> },
      { key: 'rooms', label: '考场安排', children: <section className="es-personnel">
        <header className="es-section-head"><div><h3>考场安排</h3><span>选择本次可用场地，调整已分配考场</span></div><Button disabled={readOnly} onClick={() => prepare('calendar', 'rooms')}>设置可用考场</Button></header>
        <RoomDutyWorkspace key={examId} rooms={plan.rooms} readOnly={readOnly} onAdjust={setEditingRoom} />
      </section> },
      { key: 'teachers', label: '监考安排', children: <section className="es-personnel">
        <header className="es-section-head"><div><h3>监考安排</h3><span>设置参与教师和可用时间，调整各场监考任务</span></div><Button disabled={readOnly} onClick={() => prepare('calendar', 'staff')}>设置监考教师</Button></header>
        <TeacherDutyWorkspace key={examId} workloads={workloads} readOnly={readOnly} onAdjust={(room, teacherId, swap) => { setEditingTeacherId(teacherId); setEditingSwap(swap); setEditingRoom(room) }} />
      </section> },
      { key: 'seats', label: '考生座位', children: seatSection },
      { key: 'printing', label: '打印材料', children: <section className="es-personnel">
        <header className="es-section-head"><div><h3>打印材料</h3><span>打印前自动检查安排，发现冲突会阻止打印</span></div></header>
        {check && !check.ok && <Alert type="error" showIcon message={`发现 ${check.issues.length} 项待处理问题`} action={<Button onClick={() => switchWorkspace('settings')}>处理冲突</Button>} />}
        <div className="es-print-options">
          <div><h4>准考证</h4><p>按年级、班级或考生筛选，预览并批量打印。</p><Button type="primary" disabled={!plan.rooms.length} onClick={() => setTickets(true)}>准考证打印</Button></div>
          <div><h4>监考任务单</h4><p>每位教师的时间、科目和考场安排。</p><Button disabled={!plan.rooms.length || checking} onClick={() => void printReport('duty')}>打印监考任务单</Button></div>
          <div><h4>考场表</h4><p>各场次的考场、容量、人数和监考信息。</p><Button disabled={!plan.rooms.length || checking} onClick={() => void printReport('resources')}>打印考场表</Button></div>
        </div>
      </section> },
    ]} />}
    {setup && exams.find(e => e.id === examId) && <ExamSetup exam={exams.find(e => e.id === examId)!} hasPlan={!!plan.rooms.length} initialTab={setupTab} focus={setupFocus} onClose={() => { setSetup(false); setOverviewRevision(n => n + 1); if (plan.rooms.length) void checkPlan() }} onGenerated={() => { if (examId) changeExam(examId) }} />}
    {examId && (editingRoom || editingCandidate) && <ArrangementEditor key={`${examId}-${editingRoom?.id || ''}-${editingCandidate?.id || ''}-${editingTeacherId || ''}-${editingSwap}`} examId={examId} rooms={plan.rooms} mode={workspace === 'rooms' ? 'room' : workspace === 'teachers' ? 'teacher' : 'all'} room={editingRoom} candidate={editingCandidate} initialSwap={editingSwap} initialTeacherId={editingTeacherId} onClose={() => { setEditingRoom(undefined); setEditingCandidate(undefined); setEditingTeacherId(undefined); setEditingSwap(false) }} onSaved={refresh} />}
    {tickets && examId && <AdmissionTickets examId={examId} rooms={plan.rooms} onClose={() => setTickets(false)} />}
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
