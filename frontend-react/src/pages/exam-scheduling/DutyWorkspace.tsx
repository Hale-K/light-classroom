import { useState } from 'react'
import { Button, DatePicker, Empty, Input, Pagination, Segmented, Table } from 'antd'
import { SearchOutlined, SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ExamRoomAssignment } from '@/types'

type Workload = { id: number; name: string; sessions: number; hours: string; rooms: ExamRoomAssignment[] }
type Period = '全部' | '上午' | '下午' | '晚上'
const periodOf = (room: ExamRoomAssignment): Period => (room.start_time || '') < '12:00' ? '上午' : (room.start_time || '') < '18:00' ? '下午' : '晚上'
const dateLabel = (date: string) => `${dayjs(date).format('M月D日')} 周${['日', '一', '二', '三', '四', '五', '六'][dayjs(date).day()]}`
const ordered = (rooms: ExamRoomAssignment[]) => [...rooms].sort((a, b) => a.exam_date.localeCompare(b.exam_date) || (a.start_time || '').localeCompare(b.start_time || '') || a.room_name.localeCompare(b.room_name, 'zh-CN', { numeric: true }))

function QueryBar({ keyword, date, period, placeholder, onKeyword, onDate, onPeriod, onReset, extraQuery = false }: {
  keyword: string; date?: string; period: Period; placeholder: string
  onKeyword: (value: string) => void; onDate: (value?: string) => void; onPeriod: (value: Period) => void
  onReset?: () => void; extraQuery?: boolean
}) {
  return <div className="es-duty-query">
    <Input aria-label={placeholder} placeholder={placeholder} prefix={<SearchOutlined />} allowClear value={keyword} onChange={e => onKeyword(e.target.value)} />
    <DatePicker aria-label="查询考试日期" placeholder="全部日期" value={date ? dayjs(date) : null} onChange={d => onDate(d?.format('YYYY-MM-DD'))} />
    <Segmented aria-label="查询考试时段" options={['全部', '上午', '下午', '晚上']} value={period} onChange={value => onPeriod(value as Period)} />
    {(keyword || date || period !== '全部' || extraQuery) && <Button type="text" onClick={() => { onKeyword(''); onDate(undefined); onPeriod('全部'); onReset?.() }}>清除查询</Button>}
  </div>
}

export function TeacherDutyWorkspace({ workloads, readOnly, onAdjust }: {
  workloads: Workload[]; readOnly: boolean
  onAdjust: (room: ExamRoomAssignment, teacherId: number, swap: boolean) => void
}) {
  const [teacherQuery, setTeacherQuery] = useState('')
  const [keyword, setKeyword] = useState('')
  const [date, setDate] = useState<string>()
  const [period, setPeriod] = useState<Period>('全部')
  const [selected, setSelected] = useState<number>()
  const [page, setPage] = useState(1)
  const search = keyword.trim().toLocaleLowerCase()
  const matches = (r: ExamRoomAssignment) => (!date || r.exam_date === date) && (period === '全部' || periodOf(r) === period)
    && `${r.subject_name} ${r.room_name} ${r.grade_name}`.toLocaleLowerCase().includes(search)
  const filtered = workloads.filter(t => t.name.includes(teacherQuery.trim()) && t.rooms.some(matches))
  const teacher = filtered.find(t => t.id === selected) || filtered[0]
  const duties = teacher ? ordered(teacher.rooms.filter(matches)) : []
  const dates = [...new Set(duties.map(r => r.exam_date))]
  const changeQuery = () => { setPage(1); setSelected(undefined) }
  if (!workloads.length) return <Empty description="生成安排后可查询教师监考日程" />
  return <div className="es-duty-workspace">
    <aside className="es-duty-sidebar" aria-label="监考教师名单">
      <div className="es-duty-list-heading"><strong>教师名单</strong><span>{filtered.length} / {workloads.length} 人</span></div>
      <Input aria-label="搜索监考教师" placeholder="搜索教师姓名" prefix={<SearchOutlined />} allowClear value={teacherQuery} onChange={e => { setTeacherQuery(e.target.value); changeQuery() }} />
      <div className="es-duty-list-label"><span>教师</span><span>场次 / 小时</span></div>
      <div className="es-duty-person-list">{filtered.slice((page - 1) * 10, page * 10).map(t => <button key={t.id} type="button" className={`es-duty-person${teacher?.id === t.id ? ' is-active' : ''}`} aria-pressed={teacher?.id === t.id} onClick={() => setSelected(t.id)}>
        <span className="es-duty-avatar" aria-hidden="true">{t.name.slice(0, 1)}</span><strong>{t.name}</strong><span>{t.sessions} 场<small>{t.hours} h</small></span>
      </button>)}{!filtered.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的教师" />}</div>
      <div className="es-duty-list-pagination">{filtered.length > 10 && <Pagination simple current={page} total={filtered.length} pageSize={10} onChange={p => { setPage(p); setSelected(filtered[(p - 1) * 10]?.id) }} />}</div>
    </aside>
    <section className="es-duty-detail" aria-label="教师监考日程">
      <QueryBar keyword={keyword} date={date} period={period} placeholder="查询科目、考场或年级" extraQuery={!!teacherQuery} onReset={() => { setTeacherQuery(''); changeQuery() }} onKeyword={v => { setKeyword(v); changeQuery() }} onDate={v => { setDate(v); changeQuery() }} onPeriod={v => { setPeriod(v); changeQuery() }} />
      {teacher ? <>
        <header className="es-duty-detail-head"><div><h3>{teacher.name}<span>监考日程</span></h3><p>本次考试共 {teacher.sessions} 场 · {teacher.hours} 小时</p></div><span>当前显示 {duties.length} 场 · {dates.length} 天</span></header>
        <div className="es-duty-days">{dates.map(day => <section className="es-duty-day" key={day}>
          <header><strong>{dateLabel(day)}</strong><span>{day}</span></header>
          {duties.filter(r => r.exam_date === day).map(r => <div className="es-duty-task" key={r.id}>
            <div className="es-duty-time"><span>{periodOf(r)}</span><strong>{r.start_time}–{r.end_time}</strong></div>
            <div className="es-duty-task-main"><strong>{r.subject_name}<span>{r.room_name}</span></strong><p>{r.grade_name} · {r.candidate_count} 名考生</p></div>
            <div className="es-duty-task-actions"><Button disabled={readOnly} onClick={() => onAdjust(r, teacher.id, false)}>调整监考</Button><Button type="text" icon={<SwapOutlined />} disabled={readOnly} onClick={() => onAdjust(r, teacher.id, true)}>交换场次</Button></div>
          </div>)}
        </section>)}</div>
      </> : <Empty description="没有符合查询条件的监考安排" />}
    </section>
  </div>
}

export function RoomDutyWorkspace({ rooms, readOnly, onAdjust }: { rooms: ExamRoomAssignment[]; readOnly: boolean; onAdjust: (room: ExamRoomAssignment) => void }) {
  const [keyword, setKeyword] = useState('')
  const [date, setDate] = useState<string>()
  const [period, setPeriod] = useState<Period>('全部')
  const [selected, setSelected] = useState<string>()
  const [sessionPage, setSessionPage] = useState(1)
  const search = keyword.trim().toLocaleLowerCase()
  const filtered = ordered(rooms.filter(r => (!date || r.exam_date === date) && (period === '全部' || periodOf(r) === period)
    && `${r.subject_name} ${r.room_name} ${r.grade_name} ${r.invigilator_names.join(' ')}`.toLocaleLowerCase().includes(search)))
  const groups = new Map<string, ExamRoomAssignment[]>()
  for (const room of filtered) {
    const key = `${room.exam_date}|${room.start_time}|${room.end_time}|${room.subject_id}`
    groups.set(key, [...(groups.get(key) || []), room])
  }
  const key = selected && groups.has(selected) ? selected : groups.keys().next().value
  const rows = key ? groups.get(key)! : []
  const first = rows[0]
  const sessions = [...groups.entries()]
  const visibleSessionPage = Math.min(sessionPage, Math.max(1, Math.ceil(sessions.length / 6)))
  if (!rooms.length) return <Empty description="生成安排后可查询考场分配" />
  return <>
    <QueryBar keyword={keyword} date={date} period={period} placeholder="查询科目、考场、年级或监考教师" onKeyword={v => { setKeyword(v); setSelected(undefined); setSessionPage(1) }} onDate={v => { setDate(v); setSelected(undefined); setSessionPage(1) }} onPeriod={v => { setPeriod(v); setSelected(undefined); setSessionPage(1) }} />
    <div className="es-duty-workspace es-room-workspace">
      <aside className="es-duty-sidebar" aria-label="考试场次列表"><div className="es-duty-list-heading"><strong>考试场次</strong><span>{groups.size} 场</span></div>
        <div className="es-duty-session-list">{sessions.slice((visibleSessionPage - 1) * 6, visibleSessionPage * 6).map(([id, list]) => <button type="button" key={id} className={`es-duty-session${key === id ? ' is-active' : ''}`} aria-pressed={key === id} onClick={() => setSelected(id)}>
          <span>{dateLabel(list[0].exam_date)}</span><strong>{list[0].subject_name}<small>{list.length} 个考场</small></strong><span>{list[0].start_time}–{list[0].end_time}</span>
        </button>)}
        {!groups.size && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的场次" />}</div>
        <div className="es-duty-session-pagination">{sessions.length > 6 && <Pagination simple current={visibleSessionPage} total={sessions.length} pageSize={6} onChange={p => { setSessionPage(p); setSelected(sessions[(p - 1) * 6]?.[0]) }} />}</div>
      </aside>
      <section className="es-duty-detail" aria-label="场次考场安排">
        {first ? <><header className="es-duty-detail-head"><div><h3>{first.subject_name}<span>{dateLabel(first.exam_date)}</span></h3><p>{first.start_time}–{first.end_time}</p></div><span>当前结果 {rows.length} 个考场 · {rows.reduce((n, r) => n + r.candidate_count, 0)} 名考生</span></header>
          <Table size="small" tableLayout="fixed" rowKey="id" dataSource={rows} pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }} scroll={{ x: 620 }} columns={[
            { title: '考场', dataIndex: 'room_name', width: '22%' }, { title: '年级', dataIndex: 'grade_name', width: '20%' },
            { title: '考生 / 座位', width: '22%', render: (_, r) => <div className="es-duty-capacity"><span>{r.candidate_count} / {r.capacity}</span><div><i style={{ width: `${Math.min(100, r.capacity ? r.candidate_count / r.capacity * 100 : 0)}%` }} /></div></div> },
            { title: '监考教师', width: '26%', render: (_, r) => r.invigilator_names.join('、') || '待安排' },
            { title: '操作', width: '10%', render: (_, r) => <Button type="link" disabled={readOnly} onClick={() => onAdjust(r)}>调整</Button> },
          ]} />
        </> : <Empty description="没有符合查询条件的考场安排" />}
      </section>
    </div>
  </>
}
