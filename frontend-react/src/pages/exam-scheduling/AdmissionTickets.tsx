import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Input, Modal, Select, Space, Spin } from 'antd'
import { examSchedulingApi } from '@/api'
import type { AdmissionTicketPage, ExamRoomAssignment } from '@/types'
import { printExamDocument, TicketDocument } from './print'

export default function AdmissionTickets({ examId, rooms, onClose }: { examId: number; rooms: ExamRoomAssignment[]; onClose: () => void }) {
  const { message } = App.useApp()
  const [keyword, setKeyword] = useState('')
  const [grade, setGrade] = useState<number>()
  const [classId, setClassId] = useState<number>()
  const [classOptions, setClassOptions] = useState<NonNullable<AdmissionTicketPage['class_options']>>([])
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState<AdmissionTicketPage>()
  const [error, setError] = useState('')
  const request = useRef(0)
  const load = async (filters: { search?: string; gradeId?: number; selectedClass?: number } = { search: keyword, gradeId: grade, selectedClass: classId }) => {
    const { search, gradeId, selectedClass } = filters
    const seq = ++request.current
    setBusy(true); setError('')
    try {
      const first = await examSchedulingApi.tickets(examId, { keyword: search, grade_id: gradeId, class_id: selectedClass, page_size: 200 })
      const items = [...first.items]
      for (let page = 2; page <= first.pagination.total_pages; page++) {
        if (seq !== request.current) return
        const next = await examSchedulingApi.tickets(examId, { keyword: search, grade_id: gradeId, class_id: selectedClass, page_size: 200, page })
        if (next.revision !== first.revision) throw new Error('座位安排刚刚发生变化，请重新加载准考证')
        items.push(...next.items)
      }
      if (seq === request.current) { setData({ ...first, items }); setClassOptions(first.class_options || []) }
    } catch (e) { if (seq === request.current) { setData(undefined); setError(e instanceof Error ? e.message : '准考证加载失败') } }
    finally { if (seq === request.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { request.current++ } }, [examId])
  const print = async () => {
    if (!data) return
    setBusy(true)
    try {
      const current = await examSchedulingApi.tickets(examId, { page_size: 1 })
      if (current.revision !== data.revision) throw new Error('安排已更新，请重新加载后打印')
      await printExamDocument(`${data.exam_name}准考证`, <TicketDocument school={data.school_name} exam={data.exam_name} tickets={data.items} />)
    } catch (e) { message.error(e instanceof Error ? e.message : '打印失败') }
    finally { setBusy(false) }
  }
  return <Modal className="es-tickets-modal" title="准考证打印" open width={850} onCancel={onClose} footer={<Space><Button onClick={onClose}>关闭</Button><Button type="primary" disabled={!data?.items.length || busy} onClick={print}>打印全部 {data?.items.length || 0} 张</Button></Space>}>
    <div className="es-ticket-filters"><Select aria-label="准考证年级" allowClear placeholder="全部年级" value={grade} onChange={v => { setGrade(v); setClassId(undefined); setData(undefined); void load({ search: keyword, gradeId: v }) }} options={[...new Map(rooms.map(r => [r.grade_id, { value: r.grade_id, label: r.grade_name }])).values()]} /><Select aria-label="准考证班级" allowClear placeholder="全部班级" value={classId} onChange={v => { setClassId(v); setData(undefined); void load({ search: keyword, gradeId: grade, selectedClass: v }) }} options={classOptions.filter(c => !grade || c.grade_id === grade).map(c => ({ value: c.id, label: c.name }))} /><Input.Search aria-label="搜索准考证" placeholder="姓名或学号" allowClear value={keyword} onChange={e => { request.current++; setBusy(false); setKeyword(e.target.value); setData(undefined) }} onSearch={v => void load({ search: v, gradeId: grade, selectedClass: classId })} /><Button disabled={busy} onClick={() => void load()}>重新加载</Button></div>
    {error && <Alert showIcon type="error" message={error} />}
    <Spin spinning={busy}><div className="es-ticket-preview">{data?.items.length ? <><div className="es-muted">共 {data.items.length} 张，每位考生独立打印，使用 A4 纸张；以下预览第一张。</div><TicketDocument school={data.school_name} exam={data.exam_name} tickets={[data.items[0]]} /></> : !busy && <div className="es-empty">{data ? '没有符合条件的考生' : '请输入条件后搜索，或重新加载'}</div>}</div></Spin>
  </Modal>
}
