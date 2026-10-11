import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Collapse, DatePicker, Form, Input, InputNumber, Modal, Radio, Select, Space, Spin, Steps, Switch, Table, Tabs, TimePicker } from 'antd'
import dayjs from 'dayjs'
import { examSchedulingApi, orgApi } from '@/api'
import type { Exam, ExamInvigilatorEntry, ExamRoomEntry, ExamScheduleEntry, ExamSchedulingConfig, Grade } from '@/types'
import ExamRulesPanel, { DEFAULT_EXAM_RULES } from './ExamRulesPanel'
import TeacherUnavailableTimes from './TeacherUnavailableTimes'
import SubjectTimeSlots from './SubjectTimeSlots'

interface Props { exam: Exam; hasPlan: boolean; initialTab?: string; focus?: 'rooms' | 'staff'; onClose: () => void; onGenerated: () => void }

export default function ExamSetup({ exam, hasPlan, initialTab = 'calendar', focus, onClose, onGenerated }: Props) {
  const { message } = App.useApp()
  const [step, setStep] = useState(focus ? 1 : 0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [config, setConfig] = useState<ExamSchedulingConfig>()
  const [grades, setGrades] = useState<Grade[]>([])
  const [subjects, setSubjects] = useState<Array<{ id: number; name: string; grade_ids: number[] }>>([])
  const [rooms, setRooms] = useState<ExamRoomEntry[]>([])
  const [selectedRooms, setSelectedRooms] = useState<number[]>([])
  const [teachers, setTeachers] = useState<ExamInvigilatorEntry[]>([])
  const [slots, setSlots] = useState<ExamScheduleEntry[]>([])
  const [teacherSearch, setTeacherSearch] = useState('')
  const [editing, setEditing] = useState<ExamInvigilatorEntry>()
  const [review, setReview] = useState<{ student_count: number; room_count: number; session_count: number }>()
  const live = useRef(true)
  useEffect(() => {
    live.current = true
    Promise.all([examSchedulingApi.config(exam.id), orgApi.grades(), examSchedulingApi.allRooms(), examSchedulingApi.venues(exam.id), examSchedulingApi.invigilators(exam.id), examSchedulingApi.subjects(exam.id), focus === 'staff' ? examSchedulingApi.preview(exam.id) : Promise.resolve([])])
      .then(([data, gradeRows, catalog, venues, staff, subjectRows, preview]) => {
        if (!live.current) return
        setConfig({ ...data, rules: { ...DEFAULT_EXAM_RULES, reference_mode: 'auto', ...data.rules }, subject_ids: data.subject_ids?.length ? data.subject_ids : subjectRows.map(s => s.id), candidate_mode: data.candidate_mode || 'grade', schedule_mode: data.candidate_mode !== 'choices' ? 'custom' : data.schedule_mode || 'custom', sessions: data.sessions.length ? data.sessions : [{ start_time: '09:00', end_time: '11:00' }, { start_time: '14:30', end_time: '16:30' }], start_date: data.start_date || dayjs().format('YYYY-MM-DD') })
        setSubjects(subjectRows); setSlots(preview)
        setGrades(gradeRows); setRooms(catalog); setTeachers(staff)
        const availableRoomIds = catalog.filter(r => r.status === 'available').map(r => r.id)
        const savedRoomIds = catalog.filter(r => r.status === 'available' && venues.rooms.some(v => v.name === r.name)).map(r => r.id)
        // A new exam is a school-wide event by default. Keep an already confirmed
        // custom scope intact, while defaulting an unconfigured exam to every usable room.
        setSelectedRooms(venues.confirmed && (savedRoomIds.length || hasPlan) ? savedRoomIds : availableRoomIds)
      }).catch(e => live.current && setError(e instanceof Error ? e.message : '准备信息加载失败'))
      .finally(() => live.current && setBusy(false))
    return () => { live.current = false }
  }, [exam.id, focus])
  const update = (patch: Partial<ExamSchedulingConfig>) => {
    if (config) {
      const next = { ...config, ...patch }
      const preferences = Object.fromEntries(Object.entries(next.rules?.subject_time_slots || {}).filter(([id]) => next.subject_ids?.includes(Number(id))))
      if (patch.schedule_mode === 'school') next.rules = { ...DEFAULT_EXAM_RULES, ...next.rules, subject_time_slots: {} }
      else next.rules = { ...DEFAULT_EXAM_RULES, ...next.rules, subject_time_slots: preferences }
      setConfig(next)
    }
    setError('')
  }
  const body = config && { exam_id: exam.id, grade_ids: config.grade_ids, start_date: config.start_date!, sessions: config.sessions,
    subject_ids: config.subject_ids, candidate_mode: config.candidate_mode, schedule_mode: config.schedule_mode,
    excluded_dates: config.excluded_dates, invigilators_per_room: config.invigilators_per_room, rules: config.rules }
  const next = async () => {
    if (!config || !body) return
    if (focus === 'staff') { onClose(); return }
    setBusy(true); setError('')
    try {
      if (step === 0) {
        await examSchedulingApi.saveConfig(exam.id, config)
        const preview = await examSchedulingApi.preview(exam.id)
        setSlots(preview); setStep(1)
      } else if (step === 1) {
        const selected = rooms.filter(r => selectedRooms.includes(r.id))
        await examSchedulingApi.saveVenues(exam.id, selected.map(r => ({ name: r.name, capacity: r.capacity, source_type: r.source_class_id ? 'classroom' : 'custom', source_class_id: r.source_class_id })))
        if (focus === 'rooms') { message.success('可用考场已保存'); onClose(); return }
        const result = await examSchedulingApi.preflight(body)
        setReview(result); setStep(2)
      } else {
        await examSchedulingApi.generatePlan({ ...body, room: '按已确认考场分配' })
        message.success('安排已生成'); onGenerated(); onClose()
      }
    } catch (e) { setError(e instanceof Error ? e.message : '操作失败，请重试') }
    finally { if (live.current) setBusy(false) }
  }
  const saveTeacher = async () => {
    if (!editing) return
    setBusy(true)
    try {
      await examSchedulingApi.saveInvigilator(exam.id, editing.teacher_id, editing)
      setTeachers(rows => rows.map(r => r.teacher_id === editing.teacher_id ? editing : r))
      setEditing(undefined); setError('')
    } catch (e) { message.error(e instanceof Error ? e.message : '保存失败') }
    finally { setBusy(false) }
  }
  const invalid = !config?.grade_ids.length || !config.subject_ids?.length || !config.start_date || !config.sessions.length || config.sessions.some(s => !s.start_time || !s.end_time)
  const availableRooms = rooms.filter(r => r.status === 'available')
  const gaokaoRooms = config?.rules?.room_mode === 'gaokao'
  const seatLimit = config?.rules?.room_seat_limit || 30
  const examCapacity = (capacity: number) => gaokaoRooms ? Math.min(capacity, seatLimit) : capacity
  const selected = rooms.filter(r => selectedRooms.includes(r.id))
  const selectedSeatCount = selected.reduce((total, room) => total + examCapacity(room.capacity), 0)
  const availableSeatCount = availableRooms.reduce((total, room) => total + examCapacity(room.capacity), 0)
  const isWholeSchoolScope = selectedRooms.length === availableRooms.length && availableRooms.length > 0 && availableRooms.every(room => selectedRooms.includes(room.id))
  const slotOptions = [...new Map(slots.map(s => [`${s.exam_date}#${s.session_index}`, { value: `${s.exam_date}#${s.session_index}`, label: `${s.exam_date} ${s.start_time}–${s.end_time}` }])).values()]
  let firstAvailable = config?.start_date ? dayjs(config.start_date) : undefined
  while (firstAvailable && (firstAvailable.day() === 0 || firstAvailable.day() === 6 || config?.excluded_dates.includes(firstAvailable.format('YYYY-MM-DD')))) firstAvailable = firstAvailable.add(1, 'day')
  return <Modal className="es-setup-modal" title={`${focus === 'rooms' ? '可用考场' : focus === 'staff' ? '监考教师' : '准备排考'} · ${exam.name}`} open width={960} onCancel={onClose} maskClosable={false} closable={!busy} keyboard={!busy}
    footer={<div>{error && <Alert className="es-setup-error" type="error" showIcon message="检查未通过" description={error} action={step === 1 ? <Button size="small" onClick={() => setStep(0)}>返回检查参考范围与日程</Button> : undefined} />}<Space><Button disabled={busy} onClick={onClose}>稍后继续</Button>{step > 0 && !focus && <Button disabled={busy} onClick={() => { setStep(step - 1); setError('') }}>上一步</Button>}<Button type="primary" loading={busy} disabled={!config || (step === 0 && invalid) || (step === 1 && focus !== 'staff' && !selectedRooms.length)} onClick={next}>{focus === 'rooms' ? '保存考场' : focus === 'staff' ? '完成设置' : ['保存日程，下一步', '检查安排，下一步', hasPlan ? '确认重新生成' : '生成安排'][step]}</Button></Space></div>}>
    {!focus && <Steps size="small" current={step} items={[{ title: '考试日程' }, { title: '考场与人员' }, { title: '检查并生成' }]} />}
    <Spin spinning={busy}><div className="es-setup-body">
      {step === 1 && !focus && slots.length > 0 && <>
        <Alert className="es-scope-summary" showIcon type="info" message={`实际日程：${slots[0].exam_date} 至 ${slots[slots.length - 1].exam_date}`} description="已跳过周末、禁排日期和考生已有考试的占用，保留指定上午或下午时段。请核对以下实际日期。" />
        <Collapse items={[{ key: 'preview', label: `查看实际考试日程（${slots.length} 场）`, children: <Table size="small" rowKey="id" dataSource={slots} pagination={false} columns={[{ title: '日期', dataIndex: 'exam_date' }, { title: '时间', render: (_, s) => `${s.start_time}–${s.end_time}` }, { title: '年级', dataIndex: 'grade_name' }, { title: '科目', dataIndex: 'subject_name' }]} /> }]} />
      </>}
      {config && step === 0 && <Tabs defaultActiveKey={initialTab} items={[{ key: 'calendar', label: '考试日程', children: <Form layout="vertical">
        <Alert className="es-scope-summary" type="info" showIcon message={`${exam.academic_year}学年 · 第${exam.term}学期 · ${config.candidate_mode === 'choices' ? '按学生选科考试' : '全年级统一考试'}`} description={config.rules?.reference_mode === 'manual' ? '本次考试采用已指定的参考范围。可在特殊考试设置中恢复自动跟随。' : config.environment?.message || '参考范围跟随本次考试配置；特殊考试可在下方调整。'} />
        <div className="es-form-grid"><Form.Item label="参考年级" required><Select aria-label="参考年级" mode="multiple" value={config.grade_ids} onChange={grade_ids => update({ grade_ids, subject_ids: config.subject_ids?.filter(id => subjects.some(s => s.id === id && s.grade_ids.some(g => grade_ids.includes(g)))) })} options={grades.map(g => ({ value: g.id, label: g.name }))} /></Form.Item>
        <Form.Item label="开始日期" required extra={firstAvailable ? `从 ${firstAvailable.format('YYYY-MM-DD')} 起寻找可用场次；跳过周末和禁排日期，已有考试占用自动顺延。` : undefined}><DatePicker aria-label="开始日期" value={config.start_date ? dayjs(config.start_date) : null} onChange={d => update({ start_date: d?.format('YYYY-MM-DD') })} /></Form.Item></div>
        <Form.Item label="每天的考试场次" required>{config.sessions.map((s, i) => <div className="es-session-edit" key={i}><span>第 {i + 1} 场</span><TimePicker.RangePicker format="HH:mm" minuteStep={5} value={s.start_time && s.end_time ? [dayjs(`2000-01-01T${s.start_time}`), dayjs(`2000-01-01T${s.end_time}`)] : null} onChange={v => update({ sessions: config.sessions.map((r, j) => j === i ? { start_time: v?.[0]?.format('HH:mm') || '', end_time: v?.[1]?.format('HH:mm') || '' } : r) })} /><Button disabled={config.sessions.length === 1} onClick={() => update({ sessions: config.sessions.filter((_, j) => j !== i) })}>删除</Button></div>)}<Button size="small" disabled={config.sessions.length >= 4} onClick={() => update({ sessions: [...config.sessions, { start_time: '17:00', end_time: '18:00' }] })}>＋ 添加场次</Button></Form.Item>
        <Form.Item label="考试科目" required><Select aria-label="考试科目" mode="multiple" value={config.subject_ids} onChange={subject_ids => update({ subject_ids })} options={subjects.filter(s => s.grade_ids.some(id => config.grade_ids.includes(id))).map(s => ({ value: s.id, label: s.name }))} /></Form.Item>
        <Form.Item><SubjectTimeSlots ids={config.subject_ids || []} subjects={subjects} sessions={config.sessions} value={config.rules?.subject_time_slots || {}} disabled={config.schedule_mode !== 'custom'} onChange={subject_time_slots => update({ rules: { ...DEFAULT_EXAM_RULES, ...config.rules, subject_time_slots } })} /></Form.Item>
        <Form.Item label="不安排考试的日期"><DatePicker multiple value={config.excluded_dates.map(d => dayjs(d))} onChange={dates => update({ excluded_dates: dates?.map(d => d.format('YYYY-MM-DD')) || [] })} /></Form.Item>
        <Form.Item label="考场编排"><Space wrap><Select<'school' | 'gaokao'> aria-label="考场编排" style={{ width: 180 }} value={gaokaoRooms ? 'gaokao' : 'school'} onChange={room_mode => update({ rules: { ...DEFAULT_EXAM_RULES, ...config.rules, room_mode, ...(room_mode === 'gaokao' ? { same_subject_same_time: true } : {}) }, ...(room_mode === 'gaokao' ? { invigilators_per_room: Math.max(2, config.invigilators_per_room) } : {}) })} options={[{ value: 'gaokao', label: '高考模拟' }, { value: 'school', label: '按教室容量' }]} />{gaokaoRooms && <Select<25 | 30> aria-label="每场座位数" style={{ width: 140 }} value={seatLimit} onChange={room_seat_limit => update({ rules: { ...DEFAULT_EXAM_RULES, ...config.rules, room_seat_limit } })} options={[{ value: 30, label: '每场最多30人' }, { value: 25, label: '每场最多25人' }]} />}</Space></Form.Item>
        <Form.Item label="每个考场的监考人数"><InputNumber aria-label="每个考场的监考人数" min={gaokaoRooms ? 2 : 1} max={3} value={config.invigilators_per_room} onChange={v => update({ invigilators_per_room: v || 1 })} /></Form.Item>
        <Collapse ghost items={[{ key: 'advanced', label: '选科与特殊考试设置', children: <><Form.Item label="参考范围"><Radio.Group aria-label="参考范围" optionType="button" buttonStyle="solid" value={config.rules?.reference_mode === 'manual' ? config.candidate_mode : 'auto'} onChange={e => { const mode = e.target.value; const candidate_mode = mode === 'auto' ? config.environment?.recommended_candidate_mode || 'grade' : mode as 'grade' | 'choices'; update({ candidate_mode, rules: { ...DEFAULT_EXAM_RULES, ...config.rules, reference_mode: mode === 'auto' ? 'auto' : 'manual' }, ...(candidate_mode === 'grade' ? { schedule_mode: 'custom' as const } : {}) }) }} options={[{ value: 'auto', label: '跟随学期配置' }, { value: 'grade', label: '全年级统一考试' }, { value: 'choices', label: '按学生选科考试' }]} /><p className="es-muted">常规考试无需修改。选科考试要求学生已确认选科；高考模拟考场不会改变参考范围。</p></Form.Item><div className="es-form-grid"><Form.Item label="排考策略"><Select value={config.schedule_mode} onChange={schedule_mode => update({ schedule_mode })} options={[{ value: 'custom', label: '普通学校考试' }, { value: 'school', label: '选科同步排考（按学校选科模式）', disabled: config.candidate_mode !== 'choices' }]} /></Form.Item></div>{config.schedule_mode === 'school' && config.candidate_mode === 'grade' && <Alert type="warning" showIcon message="当前按年级全体学生安排" description="每个已选科目都会按该年级全体学生计算座位；如果物理、历史等科目按学生选科参加，请改为“按已确认选科安排”。" />}</> }]} />
      </Form> }, { key: 'rules', label: '排考规则', children: <ExamRulesPanel value={config.rules} onChange={rules => update({ rules })} /> }]} />}
      {step === 1 && <Tabs defaultActiveKey={focus || 'rooms'} items={[{ key: 'rooms', label: `考场 · 已选 ${selected.length} 间 / ${selectedSeatCount} 座`, children: <><Alert showIcon type={isWholeSchoolScope ? 'info' : 'warning'} message={isWholeSchoolScope ? `统考范围：已纳入全部 ${availableRooms.length} 间可用考场` : `自定义考场范围：已选 ${selected.length} / ${availableRooms.length} 间可用考场`} description={isWholeSchoolScope ? `本场可用 ${availableSeatCount} 个考试座位${gaokaoRooms ? `，每间最多 ${seatLimit} 人` : ''}；维修或停用空间不纳入。` : `本场可用 ${selectedSeatCount} 个考试座位${gaokaoRooms ? `，每间最多 ${seatLimit} 人` : ''}。统考建议纳入全部可用考场。`} action={!isWholeSchoolScope ? <Button size="small" onClick={() => setSelectedRooms(availableRooms.map(room => room.id))}>纳入全部可用考场</Button> : undefined} /><Table size="small" rowKey="id" dataSource={rooms} rowSelection={{ selectedRowKeys: selectedRooms, onChange: keys => setSelectedRooms(keys.map(Number)), getCheckboxProps: r => ({ disabled: r.status !== 'available' }) }} columns={[{ title: '考场', dataIndex: 'name' }, { title: '位置', dataIndex: 'building', render: v => v || '—' }, { title: '教室容量', dataIndex: 'capacity' }, { title: '考试座位', render: (_, r) => examCapacity(r.capacity) }, { title: '状态', dataIndex: 'status', render: v => ({ available: '可用', maintenance: '维修中', disabled: '停用' })[v as string] }]} pagination={{ pageSize: 8, showSizeChanger: false }} scroll={{ x: 480 }} /><div className="es-muted">考场按学校空间资源统一选择；同一考场可供不同场次使用，系统会检查同一时间的占用。</div></> },
      { key: 'staff', label: `监考教师 · ${teachers.filter(t => t.enabled && t.account_status === 'active').length} 人参与`, children: <><Input.Search aria-label="搜索监考教师" placeholder="搜索教师" allowClear value={teacherSearch} onChange={e => setTeacherSearch(e.target.value)} /><Table size="small" rowKey="teacher_id" dataSource={teachers.filter(t => t.teacher_name.includes(teacherSearch))} columns={[{ title: '教师', dataIndex: 'teacher_name' }, { title: '参与监考', render: (_, t) => t.enabled && t.account_status === 'active' ? '参与' : '排除' }, { title: '不可用场次', render: (_, t) => t.unavailable_slots.length }, { title: '休假', render: (_, t) => t.leave_start ? `${t.leave_start} 至 ${t.leave_end}` : '—' }, { title: '操作', render: (_, t) => <Button type="link" disabled={t.account_status !== 'active'} onClick={() => setEditing({ ...t })}>设置</Button> }]} pagination={{ pageSize: 8, showSizeChanger: false }} scroll={{ x: 560 }} /></> }].filter(item => !focus || item.key === focus)} />}
      {step === 2 && review && <><Alert showIcon type="success" message="配置检查通过，可以生成安排" /><div className="es-review"><div><strong>{review.student_count}</strong><span>名参考学生</span></div><div><strong>{review.session_count}</strong><span>个科目场次</span></div><div><strong>{review.room_count}</strong><span>个考场场次</span></div></div><Table size="small" rowKey="id" dataSource={slots} pagination={{ pageSize: 6, showSizeChanger: false }} columns={[{ title: '日期', dataIndex: 'exam_date' }, { title: '时间', render: (_, s) => `${s.start_time}–${s.end_time}` }, { title: '年级', dataIndex: 'grade_name' }, { title: '科目', dataIndex: 'subject_name' }]} />{hasPlan && <Alert showIcon type="warning" message="重新生成将替换现有考场、监考和座位安排，包括手动调整。" />}</>}
    </div></Spin>
    <Modal title={editing ? `${editing.teacher_name} · 可用时间` : ''} open={!!editing} onCancel={() => setEditing(undefined)} onOk={saveTeacher} confirmLoading={busy} okText="保存" cancelText="取消">
      {editing && <Form layout="vertical"><Form.Item label="参与本次监考"><Switch checked={editing.enabled} onChange={enabled => setEditing({ ...editing, enabled })} /></Form.Item><Form.Item label="不可用场次"><Select mode="multiple" value={editing.unavailable_slots.filter(item => !item.startsWith('weekly#'))} options={slotOptions} onChange={unavailable_slots => setEditing({ ...editing, unavailable_slots: [...editing.unavailable_slots.filter(item => item.startsWith('weekly#')), ...unavailable_slots] })} /></Form.Item><Form.Item label="每周不可监考时段"><TeacherUnavailableTimes value={editing.unavailable_slots} onChange={unavailable_slots => setEditing({ ...editing, unavailable_slots })} /></Form.Item><Form.Item label="休假日期"><DatePicker.RangePicker value={editing.leave_start && editing.leave_end ? [dayjs(editing.leave_start), dayjs(editing.leave_end)] : null} onChange={v => setEditing({ ...editing, leave_start: v?.[0]?.format('YYYY-MM-DD') || null, leave_end: v?.[1]?.format('YYYY-MM-DD') || null })} /></Form.Item></Form>}
    </Modal>
  </Modal>
}
