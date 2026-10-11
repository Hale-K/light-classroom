import { useEffect, useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Progress, Select, Space, Spin, Switch, Table, Tabs, Tag } from 'antd'
import { examSchedulingApi } from '@/api'
import type { ExamOverview, ExamPlan, ExamRoomAssignment } from '@/types'
import { unavailableAt } from './availability'

type PlannedRoom = ExamOverview['rooms'][number]
type Item = { key: string; title: string; detail: string; start: string; end: string; examId: number; examName: string; room?: PlannedRoom; preview?: boolean }
type Row = { key: string; name: string; items: Item[]; detail?: string }
const overlap = (a: Item, b: Item) => a.start < b.end && b.start < a.end

export default function PlanningOverview({ examId, plan, revision, readOnly, onAdjust, onPrepare }: {
  examId: number; plan: ExamPlan; revision: number; readOnly: boolean; onAdjust: (room: ExamRoomAssignment, kind?: 'room' | 'teacher') => void; onPrepare: () => void
}) {
  const [data, setData] = useState<ExamOverview>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [date, setDate] = useState('')
  const [mode, setMode] = useState('calendar')
  const [external, setExternal] = useState(true)
  const [onlyOccupied, setOnlyOccupied] = useState(true)
  const [search, setSearch] = useState('')
  const [focused, setFocused] = useState<Item>()
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setData(undefined); setFocused(undefined)
    examSchedulingApi.overview(examId).then(value => {
      if (!active) return
      setData(value)
      const dates = [...new Set(value.schedules.map(s => s.exam_date))].sort()
      setDate(current => dates.includes(current) ? current : dates[0] || '')
    }).catch(e => active && setError(e instanceof Error ? e.message : '统筹视图加载失败'))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [examId, plan, revision, retry])
  const dates = [...new Set(data?.schedules.map(s => s.exam_date) || [])].sort()
  const visible = data?.schedules.filter(s => s.exam_date === date && (external || s.exam_id === examId)) || []
  const rooms = data?.rooms.filter(r => r.exam_date === date && (external || r.exam_id === examId)) || []
  const slots = [...new Map(visible.map(s => [`${s.start_time}-${s.end_time}`, { start: s.start_time, end: s.end_time }])).values()]
    .sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end))
  const rows = new Map<string, Row>()
  const ensureRow = (key: string, name: string, detail?: string) => {
    if (!rows.has(key)) rows.set(key, { key, name, items: [], detail })
    return rows.get(key)!
  }
  if (mode === 'calendar') {
    visible.forEach(s => {
      const assigned = rooms.filter(r => r.exam_schedule_id === s.id && r.exam_id === s.exam_id)
      ensureRow(String(s.grade_id), s.grade_name || `年级 ${s.grade_id}`).items.push({ key: `s-${s.exam_id}-${s.id}`, title: s.subject_name || '考试',
        detail: s.preview ? '待分配考场与监考' : `${assigned.length} 间考场 · ${assigned.reduce((n, r) => n + r.candidate_count, 0)} 人次`,
        start: s.start_time, end: s.end_time, examId: s.exam_id, examName: s.exam_name, preview: s.preview, room: assigned[0] })
    })
  } else {
    if (mode === 'rooms') data?.venues.forEach(v => ensureRow(v.name, v.name, `${v.capacity} 座${v.status && v.status !== 'available' ? ' · 不可用' : ''}`))
    else data?.teachers.forEach(t => ensureRow(String(t.id), t.name))
    rooms.forEach(r => {
      const item: Item = { key: `r-${r.id}`, title: `${r.grade_name} · ${r.subject_name}`, detail: mode === 'rooms' ? `${r.candidate_count}/${r.capacity} 人 · ${r.invigilator_names.join('、') || '缺少监考'}` : r.room_name,
        start: r.start_time || '', end: r.end_time || '', examId: r.exam_id, examName: r.exam_name, room: r }
      if (mode === 'rooms') ensureRow(r.room_name, r.room_name, `${r.capacity} 座`).items.push(item)
      else r.invigilator_ids.forEach((id, i) => ensureRow(String(id), r.invigilator_names[i] || `教师 ${id}`).items.push(item))
    })
  }
  const displayed = [...rows.values()].filter(row => (!onlyOccupied || row.items.length) && (!search || `${row.name} ${row.items.map(i => `${i.title} ${i.examName} ${i.detail}`).join(' ')}`.includes(search)))
  const blocked = (row: Row, slot: { start: string; end: string }) => {
    if (mode === 'rooms') return data?.venues.some(v => v.name === row.key && v.status && v.status !== 'available') ? '不可用' : '—'
    if (mode !== 'teachers') return '—'
    const teacher = data?.teachers.find(t => String(t.id) === row.key)
    if (teacher?.leave_start && teacher.leave_end && teacher.leave_start <= date && date <= teacher.leave_end) return '休假'
    return visible.some(s => s.exam_id === examId && s.start_time === slot.start && s.end_time === slot.end && unavailableAt(teacher?.unavailable_slots || [], date, s.start_time, s.end_time, s.session_index)) ? '不可用' : '—'
  }
  const conflicts = new Set<string>()
  if (mode !== 'calendar') for (const row of rows.values()) row.items.forEach((a, index) => row.items.slice(index + 1).forEach(b => {
    if (overlap(a, b)) { conflicts.add(a.key); conflicts.add(b.key) }
  }))
  const currentRooms = rooms.filter(r => r.exam_id === examId)
  const capacity = currentRooms.reduce((n, r) => n + r.capacity, 0)
  const occupied = currentRooms.reduce((n, r) => n + r.candidate_count, 0)
  const teacherRows = [...new Map(rooms.flatMap(r => r.invigilator_ids.map((id, i) => [id, r.invigilator_names[i]] as const))).entries()]
    .map(([id, name]) => ({ id, name, count: rooms.filter(r => r.invigilator_ids.includes(id)).length }))
    .sort((a, b) => b.count - a.count || a.id - b.id)
  return <section className="es-personnel es-planning"><header className="es-section-head"><div><h3>统筹视图</h3><span>蓝色为本次考试，灰色为其他考试；点击本次安排进入对应操作页。</span></div><Space wrap><Select aria-label="统筹日期" value={date || undefined} placeholder="考试日期" onChange={setDate} options={dates.map(d => ({ value: d, label: d }))} style={{ minWidth: 140 }} /><Space size="small"><Switch size="small" checked={external} onChange={setExternal} aria-label="显示其他考试" /><span>其他考试</span></Space></Space></header>
    <Spin spinning={loading}>
      {error ? <Alert type="error" showIcon message={error} action={<Button onClick={() => setRetry(n => n + 1)}>重试</Button>} /> : !data || !dates.length ? !loading && <Empty description="设置考试日程后，在这里预览安排"><Button disabled={readOnly} onClick={onPrepare}>准备考试</Button></Empty> : <>
        <Tabs activeKey={mode} onChange={key => { setMode(key); setSearch('') }} items={[{ key: 'calendar', label: '考试日程' }, { key: 'rooms', label: '考场占用' }, { key: 'teachers', label: '监考安排' }]} />
        <div className="es-board-toolbar"><Input.Search allowClear aria-label="搜索统筹安排" placeholder={mode === 'calendar' ? '搜索年级或科目' : mode === 'rooms' ? '搜索考场或科目' : '搜索教师或考场'} value={search} onChange={e => setSearch(e.target.value)} /><Space><Switch size="small" checked={onlyOccupied} onChange={setOnlyOccupied} aria-label="只看有安排" /><span>只看有安排</span></Space><Tag color={conflicts.size ? 'error' : 'default'}>{conflicts.size ? `${conflicts.size} 项时段重叠` : '时段占用一目了然'}</Tag></div>
        <div className="es-board-scroll" tabIndex={0} aria-label="考试统筹时间网格"><table className="es-board"><thead><tr><th>{({ calendar: '年级', rooms: '考场', teachers: '教师' })[mode]}</th>{slots.map(s => <th key={`${s.start}-${s.end}`}>{s.start}–{s.end}</th>)}</tr></thead><tbody>{displayed.map(row => <tr key={row.key}><th scope="row"><strong>{row.name}</strong>{row.detail && <small>{row.detail}</small>}{mode === 'teachers' && <small className={row.items.length > data.rules.teacher_daily_limit ? 'es-overload' : ''}>{row.items.length} 场 / 上限 {data.rules.teacher_daily_limit}{row.items.length > data.rules.teacher_daily_limit ? ' · 超出上限' : ''}</small>}</th>{slots.map(slot => <td key={`${slot.start}-${slot.end}`}>{row.items.filter(i => i.start === slot.start && i.end === slot.end).length ? row.items.filter(i => i.start === slot.start && i.end === slot.end).map(item => <button type="button" key={item.key} className={`es-board-item ${item.examId !== examId ? 'es-board-external' : ''} ${conflicts.has(item.key) ? 'es-board-conflict' : ''}`} disabled={item.examId !== examId || (mode !== 'calendar' && readOnly)} onClick={() => mode === 'calendar' ? setFocused(item) : item.room && onAdjust(item.room, mode === 'teachers' ? 'teacher' : 'room')}>
          <strong>{item.title}</strong><span>{item.detail}</span>{item.examId !== examId && <small>其他考试 · {item.examName}</small>}{conflicts.has(item.key) && <small>时间重叠</small>}
        </button>) : <span className="es-board-free">{blocked(row, slot)}</span>}</td>)}</tr>)}</tbody></table></div>
        {!displayed.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的安排" />}
        <div className="es-board-footer">{mode === 'teachers' ? <><span>当天监考工作量{external ? '（含其他考试）' : '（本次考试）'}</span><div className="es-workload-bars">{teacherRows.slice(0, 12).map(t => <div key={t.id}><span>{t.name}</span><Progress percent={Math.min(100, t.count / data.rules.teacher_daily_limit * 100)} status={t.count > data.rules.teacher_daily_limit ? 'exception' : 'normal'} showInfo={false} /><strong>{t.count} 场</strong></div>)}</div></> : <Space wrap><span>本次当天：</span><Tag>{visible.filter(s => s.exam_id === examId).length} 个科目场次</Tag><Tag>{currentRooms.length} 个考场场次</Tag><Tag>已用 {occupied} / {capacity} 座位人次</Tag>{data.schedules.some(s => s.preview) && <Tag color="gold">日程预览 · 尚未分配人员与座位</Tag>}</Space>}</div>
      </>}
    </Spin>
    <Modal title={focused ? `${date} ${focused.start}–${focused.end} · ${focused.title}` : '场次安排'} open={!!focused} onCancel={() => setFocused(undefined)} footer={<Button onClick={() => setFocused(undefined)}>关闭</Button>} width={800}>
      {focused?.preview ? <Empty description="日程已预览，尚未分配考场与监考"><Button type="primary" disabled={readOnly} onClick={() => { setFocused(undefined); onPrepare() }}>继续准备</Button></Empty> : <Table size="small" rowKey="id" pagination={false} scroll={{ x: 540 }} dataSource={rooms.filter(r => `s-${r.exam_id}-${r.exam_schedule_id}` === focused?.key)} columns={[{ title: '考场', dataIndex: 'room_name' }, { title: '考生 / 容量', render: (_, r: PlannedRoom) => `${r.candidate_count} / ${r.capacity}` }, { title: '监考教师', render: (_, r: PlannedRoom) => r.invigilator_names.join('、') || '待安排' }, { title: '操作', render: (_, r: PlannedRoom) => <Button type="link" disabled={readOnly} onClick={() => { setFocused(undefined); onAdjust(r) }}>查看考场安排</Button> }]} />}
    </Modal>
  </section>
}
