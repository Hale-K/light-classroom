import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { ScheduleEntry, SchedulingGridConfig, TeachingAssignment } from '@/types'
import type { GenStage, GenTraceEvent } from './scheduling-model'

interface WorkspaceClass { id: number; name: string }
interface GenerationWorkspaceProps {
  open: boolean; generating: boolean; stage: GenStage; percent: number; elapsed: number; solutions: number; summary: string; trace: GenTraceEvent[]
  assignments: TeachingAssignment[]; calendar: ScheduleEntry[]; gridConfig: SchedulingGridConfig; academicYear: string; term: string
  classes: WorkspaceClass[]; selectedClassId?: number; selectedClassName: string; onClassChange: (classId: number) => void; onClose: () => void
}
const STAGES: Array<{ code: GenStage; label: string }> = [{ code: 'validating', label: '校验资源' }, { code: 'generating', label: '自动排课' }, { code: 'refreshing', label: '整理课表' }, { code: 'done', label: '完成' }]
const SUBJECT_COLORS = ['blue', 'orange', 'green', 'violet', 'red', 'teal']
type Column = { label: string; weekday: number; parity: 'all' | 'odd' | 'even'; code: string }
type VisualRow = { type: 'day'; period: number } | { type: 'evening'; parity: 'odd' | 'even' }
function formatElapsed(seconds: number) { const value = Math.max(0, Math.floor(seconds)); return `${Math.floor(value / 60)}分 ${String(value % 60).padStart(2, '0')}秒` }
function parityMatches(entry: ScheduleEntry, column: Column, eveningParity?: 'odd' | 'even') { const entryParity = entry.week_parity || 'all'; return (!eveningParity || entryParity === 'all' || entryParity === eveningParity) && (column.parity === 'all' || entryParity === 'all' || entryParity === column.parity) }

export default function GenerationWorkspace({ open, generating, stage, percent, elapsed, solutions, summary, trace, assignments, calendar, gridConfig, academicYear, term, classes, selectedClassId, selectedClassName, onClassChange, onClose }: GenerationWorkspaceProps) {
  const subjectQueue = useMemo(() => {
    const map = new Map<number, { id: number; name: string; count: number; teacher?: string }>()
    for (const item of assignments) {
      if (item.subject_id <= 0 || item.weekly_periods <= 0) continue
      const current = map.get(item.subject_id)
      if (current) current.count += item.weekly_periods
      else map.set(item.subject_id, { id: item.subject_id, name: item.subject_name || '未命名学科', count: item.weekly_periods, teacher: item.teacher_name || undefined })
    }
    return Array.from(map.values()).sort((left, right) => right.count - left.count)
  }, [assignments])
  const totalSlots = subjectQueue.reduce((sum, subject) => sum + subject.count, 0)
  const columns = useMemo<Column[]>(() => {
    const configuredDays = Math.min(7, Math.max(1, gridConfig.days || 5)); const names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']; const result: Column[] = []
    for (let weekday = 1; weekday <= configuredDays; weekday += 1) {
      if (weekday === 6 && gridConfig.enable_saturday) result.push({ label: '单六', weekday, parity: 'odd', code: 'sat-odd' }, { label: '双六', weekday, parity: 'even', code: 'sat-even' })
      else if (weekday !== 6 || !gridConfig.enable_saturday) result.push({ label: names[weekday - 1], weekday, parity: 'all', code: `day-${weekday}` })
    }
    return result
  }, [gridConfig.days, gridConfig.enable_saturday])
  const dayRows = Math.max(1, gridConfig.periods_per_day || 1)
  const visualRows = useMemo<VisualRow[]>(() => { const rows: VisualRow[] = Array.from({ length: dayRows }, (_, period) => ({ type: 'day', period: period + 1 })); if (gridConfig.enable_evening) rows.push({ type: 'evening', parity: 'odd' }, { type: 'evening', parity: 'even' }); return rows }, [dayRows, gridConfig.enable_evening])
  const previewCapacity = columns.length * visualRows.length
  const previewQueue = useMemo(() => { const queue: Array<{ subject_name: string; teacher_name?: string; preview: boolean }> = []; for (let round = 0; queue.length < totalSlots; round += 1) { let added = false; for (const subject of subjectQueue) { if (round >= subject.count) continue; queue.push({ subject_name: subject.name, teacher_name: subject.teacher, preview: true }); added = true } if (!added) break } return queue }, [subjectQueue, totalSlots])
  const [previewPlaced, setPreviewPlaced] = useState(0)
  useEffect(() => {
    if (!open) return
    if (!generating) {
      setPreviewPlaced(previewCapacity)
      return
    }
    // percent 来自后端求解器进度事件，不再用本地定时器伪造“每格一步”。
    setPreviewPlaced(Math.min(previewCapacity, Math.max(0, Math.floor((percent / 100) * previewCapacity))))
  }, [open, generating, percent, previewCapacity])
  const displayedSlots = useMemo(() => {
    const findEntry = (column: Column, row: VisualRow) => {
      if (row.type === 'day') return calendar.find((item) => item.weekday === column.weekday && item.period === row.period && parityMatches(item, column))
      const start = gridConfig.evening_start_period || dayRows + 1; const entries = calendar.filter((item) => item.weekday === column.weekday && item.period >= start && parityMatches(item, column, row.parity)); if (!entries.length) return undefined
      return { ...entries[0], subject_name: entries.map((item) => item.subject_name || '未命名学科').join(' · '), teacher_name: entries.map((item) => item.teacher_name || '自动匹配教师').join(' · ') }
    }
    if (!generating && calendar.length) return visualRows.flatMap((row) => columns.map((column) => findEntry(column, row)))
    return Array.from({ length: previewCapacity }, (_, index) => previewQueue[index] && index < previewPlaced ? previewQueue[index] : undefined)
  }, [calendar, columns, dayRows, generating, gridConfig.evening_start_period, previewCapacity, previewPlaced, previewQueue, visualRows])
  const stageIndex = Math.max(0, STAGES.findIndex((item) => item.code === stage)); const placedCount = generating ? previewPlaced : calendar.length || totalSlots; const robotSlotIndex = Math.min(previewPlaced, Math.max(0, previewCapacity - 1)); const robotSubject = generating ? previewQueue[Math.min(previewPlaced, Math.max(0, previewQueue.length - 1))] : undefined
  const robotStyle = { '--robot-col': robotSlotIndex % Math.max(1, columns.length), '--robot-row': Math.floor(robotSlotIndex / Math.max(1, columns.length)), '--robot-days': Math.max(1, columns.length) } as CSSProperties
  if (!open) return null
  return <div className="generation-workspace" role="dialog" aria-modal="true" aria-label="自动排课工作区">
    <header className="generation-workspace-header"><div className="generation-workspace-brand"><span className="generation-workspace-mark">排</span><div><strong>自动排课工作区</strong><small>{academicYear} · 第 {term} 学期</small></div></div><div className="generation-workspace-actions"><label className="generation-class-switch">当前班级<select value={selectedClassId ?? ''} onChange={(event) => onClassChange(Number(event.target.value))} disabled={generating || !classes.length}><option value="" disabled>选择班级</option>{classes.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><span className={`generation-live-dot${generating ? ' is-live' : ''}`} /><span>{generating ? '算法运行中' : stage === 'done' ? '排课完成' : '需要调整'}</span><button type="button" onClick={onClose}>{generating ? '后台运行' : '返回排课管理'}</button></div></header>
    <main className="generation-workspace-body"><aside className="generation-subject-rail"><div className="generation-panel-title"><div><span>SUBJECT QUEUE</span><h2>待排学科</h2></div><b>{subjectQueue.length}</b></div><p className="generation-panel-desc">{selectedClassName} · 算法会根据课时、教师和排课规则逐个放入课位。</p><div className="generation-subject-list">{subjectQueue.map((subject, index) => { const subjectPlaced = previewQueue.slice(0, previewPlaced).filter((item) => item.subject_name === subject.name).length; const isCarrying = robotSubject?.subject_name === subject.name; return <div className={`generation-subject-card color-${SUBJECT_COLORS[index % SUBJECT_COLORS.length]}${isCarrying ? ' is-carrying' : subjectPlaced >= subject.count ? ' is-done' : subjectPlaced > 0 ? ' is-active' : ''}`} key={subject.id}><div className="generation-subject-icon">{subject.name.slice(0, 1)}</div><div className="generation-subject-copy"><strong>{subject.name}</strong><small>{subject.teacher || '教师待匹配'}</small><div className="generation-subject-progress"><i style={{ width: `${Math.round(subjectPlaced / subject.count * 100)}%` }} /></div></div><em>{subjectPlaced}/{subject.count}</em></div> })}{!subjectQueue.length && <div className="generation-empty">暂无可排学科，请先配置课时和任教关系。</div>}</div><div className="generation-rail-footer"><span>已放入</span><strong>{placedCount}</strong><small>/ {totalSlots} 个课位</small></div></aside>
      <section className="generation-board"><div className="generation-board-head"><div><span className="generation-eyebrow">LIVE TIMETABLE · DATABASE GRID</span><h1>{generating ? '正在生成课表' : stage === 'done' ? '课表生成完成' : '排课未完成'}</h1><p>{summary || '等待算法开始…'}</p></div><div className="generation-board-stat"><strong>{Math.round(percent)}%</strong><small>{solutions ? `${solutions} 个可行解` : '求解中'}</small></div></div><div className="generation-progress-track"><i style={{ width: `${Math.max(2, Math.min(100, percent))}%` }} /></div><div className="generation-grid" style={{ gridTemplateColumns: `92px repeat(${columns.length}, minmax(100px, 1fr))` }}><div className="generation-grid-corner">课位 / 星期</div>{columns.map((column) => <div className="generation-day" key={column.code}><strong>{column.label}</strong><small>{column.parity === 'all' ? `DAY ${String(column.weekday).padStart(2, '0')}` : column.parity === 'odd' ? 'ODD WEEK' : 'EVEN WEEK'}</small></div>)}{generating && robotSubject && <div className="generation-robot" key={`${previewPlaced}-${robotSubject.subject_name}`} style={robotStyle} aria-live="polite"><span className="generation-robot-icon">◈</span><span className="generation-robot-card"><strong>{robotSubject.subject_name}</strong><small>正在搬运至第 {visualRows[robotSlotIndex]?.type === 'day' ? `${visualRows[robotSlotIndex].period} 节` : `${visualRows[robotSlotIndex]?.parity === 'odd' ? '单周' : '双周'}晚自习`} · {columns[robotSlotIndex % columns.length]?.label}</small></span></div>}{visualRows.map((row, rowIndex) => <div className="generation-grid-row" key={`${row.type}-${row.type === 'day' ? row.period : row.parity}`}><div className="generation-period">{row.type === 'day' ? `第 ${row.period} 节` : `${row.parity === 'odd' ? '单周' : '双周'}晚自习`}<small>{row.type === 'day' ? (row.period <= Math.ceil(dayRows / 2) ? '上午' : '下午') : '晚间'}</small></div>{columns.map((column, columnIndex) => { const item = displayedSlots[rowIndex * columns.length + columnIndex]; const color = item?.subject_name ? SUBJECT_COLORS[(subjectQueue.findIndex((subject) => subject.name === item.subject_name?.split(' · ')[0]) + 6) % 6] : ''; const unavailable = row.type === 'day' ? row.period > (gridConfig.daily_periods?.[column.weekday - 1] || dayRows) : row.parity === 'odd' ? !(gridConfig.evening_daily_periods_odd?.[column.weekday - 1] || 0) : !(gridConfig.evening_daily_periods_even?.[column.weekday - 1] || 0); return <div className={`generation-slot ${item ? 'has-subject' : ''} ${item && 'preview' in item && item.preview ? 'is-preview' : ''} ${unavailable ? 'is-unavailable' : ''} color-${color}`} key={column.code}>{item ? <><strong>{item.subject_name}</strong><small>{item.teacher_name || '自动匹配教师'}</small></> : <span>{unavailable ? '不可排' : '等待课位'}</span>}</div> })}</div>)}</div><div className="generation-board-foot"><span><i className="legend live" />正在放置</span><span><i className="legend final" />已确认课位</span><span><i className="legend empty" />待计算</span><span className="generation-clock">已用时 {formatElapsed(elapsed)}</span></div></section>
      <aside className="generation-inspector"><div className="generation-panel-title"><div><span>RUN STATUS</span><h2>排课过程</h2></div><span className="generation-spinner" /></div><ol className="generation-stage-list">{STAGES.map((item, index) => <li className={index < stageIndex || stage === 'done' && item.code === 'done' ? 'is-done' : index === stageIndex ? 'is-current' : ''} key={item.code}><i>{index < stageIndex || stage === 'done' && item.code === 'done' ? '✓' : index + 1}</i><span>{item.label}</span></li>)}</ol><div className="generation-message"><strong>{generating ? '算法正在工作' : stage === 'done' ? '全部课位已保存' : '排课任务需要处理'}</strong><p>{summary || '正在等待任务状态…'}</p></div><div className="generation-trace"><div className="generation-trace-title">最近事件 <small>{trace.length}</small></div>{trace.slice(-5).reverse().map((event, index) => <div className="generation-trace-item" key={`${event.message}-${index}`}><i />{event.message || '状态已更新'}</div>)}</div><div className="generation-inspector-note"><strong>提示</strong><p>课表网格来自数据库课位结构；单六、双六和单双周晚自习均按真实配置展示。</p></div></aside>
    </main>
  </div>
}
