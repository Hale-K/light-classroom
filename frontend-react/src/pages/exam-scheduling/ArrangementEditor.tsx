import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Form, InputNumber, Modal, Select, Spin, Switch } from 'antd'
import { examSchedulingApi } from '@/api'
import type { ExamCandidateAssignment, ExamInvigilatorEntry, ExamRoomAssignment, ExamVenuePlan } from '@/types'

interface Props { examId: number; rooms: ExamRoomAssignment[]; room?: ExamRoomAssignment; candidate?: ExamCandidateAssignment; mode?: 'room' | 'teacher' | 'all'; initialSwap?: boolean; initialTeacherId?: number; onClose: () => void; onSaved: () => void }
export default function ArrangementEditor({ examId, rooms, room, candidate, mode = 'all', initialSwap = false, initialTeacherId, onClose, onSaved }: Props) {
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [venues, setVenues] = useState<ExamVenuePlan['rooms']>([])
  const [seatLimit, setSeatLimit] = useState<number>()
  const [teachers, setTeachers] = useState<ExamInvigilatorEntry[]>([])
  const [teacherIds, setTeacherIds] = useState(room?.invigilator_ids || [])
  const [name, setName] = useState(room?.room_name)
  const [targetId, setTargetId] = useState(candidate?.exam_room_assignment_id)
  const [seat, setSeat] = useState(candidate?.seat_no || 1)
  const [swap, setSwap] = useState(false)
  const [teacherSwap, setTeacherSwap] = useState(initialSwap)
  const [sourceTeacherId, setSourceTeacherId] = useState(initialTeacherId ?? room?.invigilator_ids[0])
  const [swapRoomId, setSwapRoomId] = useState<number>()
  const [swapTeacherId, setSwapTeacherId] = useState<number>()
  const [seated, setSeated] = useState<ExamCandidateAssignment[]>([])
  const seq = useRef(0)
  useEffect(() => {
    let active = true
    if (room) Promise.all([examSchedulingApi.venues(examId), examSchedulingApi.invigilators(examId), examSchedulingApi.config(examId)]).then(([v, t, c]) => { if (active) { setVenues(v.rooms); setTeachers(t); setSeatLimit(c.rules?.room_mode === 'gaokao' ? c.rules.room_seat_limit || 30 : undefined) } }).catch(e => active && setError(e instanceof Error ? e.message : '加载失败')).finally(() => active && setBusy(false))
    return () => { active = false; seq.current++ }
  }, [examId, room])
  useEffect(() => {
    if (!candidate || !targetId) return
    const id = ++seq.current; setBusy(true); setError(''); setSeated([])
    void (async () => {
      try {
        const first = await examSchedulingApi.candidates(examId, { room_assignment_id: targetId, page_size: 100 })
        const rows = [...first.items]
        for (let page = 2; page <= first.pagination.total_pages; page++) rows.push(...(await examSchedulingApi.candidates(examId, { room_assignment_id: targetId, page_size: 100, page })).items)
        if (seq.current === id) setSeated(rows)
      } catch (e) { if (seq.current === id) setError(e instanceof Error ? e.message : '座位加载失败') }
      finally { if (seq.current === id) setBusy(false) }
    })()
  }, [examId, candidate, targetId])
  const occupant = seated.find(c => c.seat_no === seat && c.id !== candidate?.id)
  const target = rooms.find(r => r.id === targetId)
  const save = async () => {
    setBusy(true); setError('')
    try {
      if (room && teacherSwap && sourceTeacherId && swapRoomId && swapTeacherId) await examSchedulingApi.swapInvigilators(examId, { first_room_id: room.id, first_teacher_id: sourceTeacherId, second_room_id: swapRoomId, second_teacher_id: swapTeacherId })
      else if (room) await examSchedulingApi.adjustRoom(examId, room.id, { ...(mode !== 'teacher' ? { room_name: name } : {}), ...(mode !== 'room' ? { invigilator_ids: teacherIds } : {}) })
      else if (candidate && targetId) await examSchedulingApi.adjustSeat(examId, candidate.id, { room_assignment_id: targetId, seat_no: seat, swap })
      onSaved(); onClose()
    } catch (e) { setError(e instanceof Error ? e.message : '调整失败') }
    finally { setBusy(false) }
  }
  return <Modal title={room ? `${mode === 'room' ? '调整考场' : mode === 'teacher' ? '调整监考' : '调整'} · ${room.room_name} · ${room.subject_name}` : `调整 ${candidate?.student_name} 的座位`} open onCancel={onClose} maskClosable={!busy} closable={!busy} onOk={save} confirmLoading={busy} okText="保存调整" cancelText="取消" okButtonProps={{ disabled: busy || (room ? teacherSwap ? !sourceTeacherId || !swapRoomId || !swapTeacherId : (mode !== 'teacher' && !name) || (mode !== 'room' && !teacherIds.length) : !targetId || !!occupant && !swap) }}>
    <Spin spinning={busy}>{error && <Alert type="error" showIcon message={error} />}
      <Form layout="vertical"><p className="es-muted">{(room || candidate)?.exam_date} · {(room || candidate)?.start_time}–{(room || candidate)?.end_time}</p>
      {room ? <>{mode !== 'teacher' && !teacherSwap && <Form.Item label="考场"><Select aria-label="调整考场" value={name} onChange={setName} options={venues.map(v => ({ value: v.name, label: `${v.name} · ${Math.min(v.capacity, seatLimit || v.capacity)} 个考试座位`, disabled: Math.min(v.capacity, seatLimit || v.capacity) < room.candidate_count }))} /></Form.Item>}{mode !== 'room' && !teacherSwap && <Form.Item label="监考教师"><Select aria-label="调整监考教师" mode="multiple" value={teacherIds} onChange={setTeacherIds} options={teachers.map(t => ({ value: t.teacher_id, label: `${t.teacher_name} · 已排 ${t.assigned_count} 场`, disabled: !t.enabled || t.account_status !== 'active' }))} /></Form.Item>}{mode !== 'room' && <><Form.Item label="与另一场次教师交换"><Switch aria-label="交换监考场次" checked={teacherSwap} onChange={setTeacherSwap} /></Form.Item>{teacherSwap && <><Form.Item label="本场要调换的教师"><Select aria-label="本场要调换的教师" value={sourceTeacherId} onChange={setSourceTeacherId} options={room.invigilator_ids.map(id => ({ value: id, label: teachers.find(t => t.teacher_id === id)?.teacher_name || `教师${id}` }))} /></Form.Item><Form.Item label="对方监考场次"><Select aria-label="对方监考场次" value={swapRoomId} onChange={id => { setSwapRoomId(id); setSwapTeacherId(undefined) }} options={rooms.filter(r => r.id !== room.id).map(r => ({ value: r.id, label: `${r.exam_date} ${r.start_time}–${r.end_time} · ${r.subject_name} · ${r.room_name}` }))} /></Form.Item><Form.Item label="对方调换的教师"><Select aria-label="对方调换的教师" value={swapTeacherId} onChange={setSwapTeacherId} options={(rooms.find(r => r.id === swapRoomId)?.invigilator_ids || []).filter(id => id !== sourceTeacherId).map(id => ({ value: id, label: teachers.find(t => t.teacher_id === id)?.teacher_name || `教师${id}` }))} /></Form.Item><Alert type="info" showIcon message="双方同时交换监考安排" description="保存前检查双方可用时间、监考冲突、学科回避和每天场数上限。任何一方不满足条件，两边都不修改。" /></>}</>}<div className="es-muted">{mode === 'room' ? '保存时检查考场容量与同时段占用。' : '保存时检查教师可用时间与其他考试占用。'}</div></> : <>
      <Form.Item label="目标考场"><Select aria-label="目标考场" value={targetId} onChange={v => { setTargetId(v); setSeat(1); setSwap(false) }} options={rooms.filter(r => r.exam_schedule_id === candidate?.exam_schedule_id).map(r => ({ value: r.id, label: `${r.room_name} · ${r.candidate_count}/${r.capacity} 人` }))} /></Form.Item>
      <Form.Item label="座位号"><InputNumber aria-label="座位号" min={1} max={target?.capacity || 1} value={seat} onChange={v => { setSeat(v || 1); setSwap(false) }} /><Button type="link" disabled={busy} onClick={() => { const free = Array.from({ length: target?.capacity || 0 }, (_, i) => i + 1).find(n => !seated.some(c => c.seat_no === n)); if (free) { setSeat(free); setSwap(false) } }}>选择首个空座</Button></Form.Item>
      {occupant ? <Alert type="warning" showIcon message={`该座位是 ${occupant.student_name} 的座位`} description={<label><Switch size="small" checked={swap} onChange={setSwap} /> 交换两人的座位</label>} /> : <div className="es-muted">{busy ? '正在确认座位' : '此座位可用'}</div>}</>}
      </Form>
    </Spin>
  </Modal>
}
