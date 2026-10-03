import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { ScheduleEntry, SchedulingGridConfig, TeachingAssignment } from '@/types'
import type { GenStage, GenTraceEvent } from './scheduling-model'

interface GenerationWorkspaceProps {
  open: boolean
  generating: boolean
  stage: GenStage
  percent: number
  elapsed: number
  solutions: number
  summary: string
  trace: GenTraceEvent[]
  assignments: TeachingAssignment[]
  calendar: ScheduleEntry[]
  gridConfig: SchedulingGridConfig
  academicYear: string
  term: string
  onClose: () => void
}

const STAGES: Array<{ code: GenStage; label: string }> = [
  { code: 'validating', label: '校验资源' },
  { code: 'generating', label: '自动排课' },
  { code: 'refreshing', label: '整理课表' },
  { code: 'done', label: '完成' },
]

const SUBJECT_COLORS = ['blue', 'orange', 'green', 'violet', 'red', 'teal']

function formatElapsed(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  return `${Math.floor(value / 60)}分 ${String(value % 60).padStart(2, '0')}秒`
}

export default function GenerationWorkspace({
  open,
  generating,
  stage,
  percent,
  elapsed,
  solutions,
  summary,
  trace,
  assignments,
  calendar,
  gridConfig,
  academicYear,
  term,
  onClose,
}: GenerationWorkspaceProps) {
  const subjectQueue = useMemo(() => {
    const map = new Map<number, { id: number; name: string; count: number; teacher?: string }>()
    for (const item of assignments) {
      if (item.subject_id <= 0 || item.weekly_periods <= 0) continue
      const current = map.get(item.subject_id)
      if (current) {
        current.count += item.weekly_periods
        continue
      }
      map.set(item.subject_id, {
        id: item.subject_id,
        name: item.subject_name || '未命名学科',
        count: item.weekly_periods,
        teacher: item.teacher_name || undefined,
      })
    }
    return Array.from(map.values()).sort((left, right) => right.count - left.count)
  }, [assignments])

  const totalSlots = subjectQueue.reduce((sum, subject) => sum + subject.count, 0)
  const previewQueue = useMemo(
    () => subjectQueue.flatMap((subject) => Array.from({ length: subject.count }, () => ({ subject_name: subject.name, teacher_name: subject.teacher, preview: true }))),
    [subjectQueue],
  )
  const [previewPlaced, setPreviewPlaced] = useState(0)
  useEffect(() => {
    if (!open) return
    setPreviewPlaced(0)
    if (!generating) return
    const timer = window.setInterval(() => {
      setPreviewPlaced((value) => Math.min(totalSlots, value + 1))
    }, 620)
    return () => window.clearInterval(timer)
  }, [open, generating, totalSlots])

  const displayedSlots = useMemo(() => {
    const days = Math.min(7, Math.max(1, gridConfig.days || 5))
    const rows = Math.min(9, Math.max(1, gridConfig.periods_per_day || 8))
    const finalEntries = calendar.filter((item) => item.weekday >= 1 && item.weekday <= days && item.period >= 1 && item.period <= rows)
    if (!generating && finalEntries.length) {
      return Array.from({ length: days * rows }, (_, index) => {
        const weekday = (index % days) + 1
        const period = Math.floor(index / days) + 1
        return finalEntries.find((item) => item.weekday === weekday && item.period === period)
      })
    }
    const preview = [] as Array<{ subject_name?: string; teacher_name?: string; preview: boolean } | undefined>
    for (let index = 0; index < days * rows; index += 1) {
      preview.push(previewQueue[index] && index < previewPlaced ? previewQueue[index] : undefined)
    }
    return preview
  }, [calendar, generating, gridConfig.days, gridConfig.periods_per_day, previewPlaced, previewQueue])

  const stageIndex = Math.max(0, STAGES.findIndex((item) => item.code === stage))
  const placedCount = generating ? previewPlaced : calendar.length || totalSlots
  const days = Math.min(7, Math.max(1, gridConfig.days || 5))
  const rows = Math.min(9, Math.max(1, gridConfig.periods_per_day || 8))
  const robotSlotIndex = Math.min(previewPlaced, Math.max(0, days * rows - 1))
  const robotSubject = generating ? previewQueue[Math.min(previewPlaced, Math.max(0, previewQueue.length - 1))] : undefined
  const robotStyle = {
    '--robot-col': robotSlotIndex % days,
    '--robot-row': Math.floor(robotSlotIndex / days),
    '--robot-days': days,
  } as CSSProperties

  if (!open) return null

  return (
    <div className="generation-workspace" role="dialog" aria-modal="true" aria-label="自动排课工作区">
      <header className="generation-workspace-header">
        <div className="generation-workspace-brand"><span className="generation-workspace-mark">排</span><div><strong>自动排课工作区</strong><small>{academicYear} · 第 {term} 学期</small></div></div>
        <div className="generation-workspace-actions">
          <span className={`generation-live-dot${generating ? ' is-live' : ''}`} />
          <span>{generating ? '算法运行中' : stage === 'done' ? '排课完成' : '需要调整'}</span>
          <button type="button" onClick={onClose}>{generating ? '后台运行' : '返回排课管理'}</button>
        </div>
      </header>

      <main className="generation-workspace-body">
        <aside className="generation-subject-rail">
          <div className="generation-panel-title"><div><span>SUBJECT QUEUE</span><h2>待排学科</h2></div><b>{subjectQueue.length}</b></div>
          <p className="generation-panel-desc">算法会根据课时、教师和排课规则逐个放入课位。</p>
          <div className="generation-subject-list">
            {subjectQueue.map((subject, index) => {
              const usedBefore = subjectQueue.slice(0, index).reduce((sum, item) => sum + item.count, 0)
              const subjectPlaced = Math.max(0, Math.min(subject.count, previewPlaced - usedBefore))
              const isCarrying = robotSubject?.subject_name === subject.name
              return <div className={`generation-subject-card color-${SUBJECT_COLORS[index % SUBJECT_COLORS.length]}${isCarrying ? ' is-carrying' : subjectPlaced >= subject.count ? ' is-done' : subjectPlaced > 0 ? ' is-active' : ''}`} key={subject.id}>
                <div className="generation-subject-icon">{subject.name.slice(0, 1)}</div>
                <div className="generation-subject-copy"><strong>{subject.name}</strong><small>{subject.teacher || '教师待匹配'}</small><div className="generation-subject-progress"><i style={{ width: `${Math.round(subjectPlaced / subject.count * 100)}%` }} /></div></div>
                <em>{subjectPlaced}/{subject.count}</em>
              </div>
            })}
            {!subjectQueue.length && <div className="generation-empty">暂无可排学科，请先配置课时和任教关系。</div>}
          </div>
          <div className="generation-rail-footer"><span>已放入</span><strong>{placedCount}</strong><small>/ {totalSlots} 个课位</small></div>
        </aside>

        <section className="generation-board">
          <div className="generation-board-head"><div><span className="generation-eyebrow">LIVE TIMETABLE</span><h1>{generating ? '正在生成课表' : stage === 'done' ? '课表生成完成' : '排课未完成'}</h1><p>{summary || '等待算法开始…'}</p></div><div className="generation-board-stat"><strong>{Math.round(percent)}%</strong><small>{solutions ? `${solutions} 个可行解` : '求解中'}</small></div></div>
          <div className="generation-progress-track"><i style={{ width: `${Math.max(2, Math.min(100, percent))}%` }} /></div>
          <div className="generation-grid" style={{ gridTemplateColumns: `92px repeat(${days}, minmax(100px, 1fr))` }}>
            <div className="generation-grid-corner">课位 / 星期</div>
            {Array.from({ length: days }, (_, index) => <div className="generation-day" key={index}><strong>{['周一', '周二', '周三', '周四', '周五', '周六', '周日'][index]}</strong><small>DAY {String(index + 1).padStart(2, '0')}</small></div>)}
            {generating && robotSubject && <div className="generation-robot" key={`${previewPlaced}-${robotSubject.subject_name}`} style={robotStyle} aria-live="polite"><span className="generation-robot-icon">◈</span><span className="generation-robot-card"><strong>{robotSubject.subject_name}</strong><small>搬运至第 {Math.floor(robotSlotIndex / days) + 1} 节 · {['周一', '周二', '周三', '周四', '周五', '周六', '周日'][robotSlotIndex % days]}</small></span></div>}
            {Array.from({ length: rows }, (_, period) => <div className="generation-grid-row" key={period}><div className="generation-period">第 {period + 1} 节<small>{period < 4 ? '上午' : '下午'}</small></div>{Array.from({ length: days }, (_, day) => { const item = displayedSlots[period * days + day]; const color = item?.subject_name ? SUBJECT_COLORS[(subjectQueue.findIndex((subject) => subject.name === item.subject_name) + 6) % 6] : ''; return <div className={`generation-slot ${item ? 'has-subject' : ''} ${item && 'preview' in item && item.preview ? 'is-preview' : ''} color-${color}`} key={day}>{item ? <><strong>{item.subject_name}</strong><small>{item.teacher_name || '自动匹配教师'}</small></> : <span>等待课位</span>}</div> })}</div>)}
          </div>
          <div className="generation-board-foot"><span><i className="legend live" />正在放置</span><span><i className="legend final" />已确认课位</span><span><i className="legend empty" />待计算</span><span className="generation-clock">已用时 {formatElapsed(elapsed)}</span></div>
        </section>

        <aside className="generation-inspector">
          <div className="generation-panel-title"><div><span>RUN STATUS</span><h2>排课过程</h2></div><span className="generation-spinner" /></div>
          <ol className="generation-stage-list">{STAGES.map((item, index) => <li className={index < stageIndex || stage === 'done' && item.code === 'done' ? 'is-done' : index === stageIndex ? 'is-current' : ''} key={item.code}><i>{index < stageIndex || stage === 'done' && item.code === 'done' ? '✓' : index + 1}</i><span>{item.label}</span></li>)}</ol>
          <div className="generation-message"><strong>{generating ? '算法正在工作' : stage === 'done' ? '全部课位已保存' : '排课任务需要处理'}</strong><p>{summary || '正在等待任务状态…'}</p></div>
          <div className="generation-trace"><div className="generation-trace-title">最近事件 <small>{trace.length}</small></div>{trace.slice(-5).reverse().map((event, index) => <div className="generation-trace-item" key={`${event.message}-${index}`}><i />{event.message || '状态已更新'}</div>)}</div>
          <div className="generation-inspector-note"><strong>提示</strong><p>这是排课过程预览。最终课表以算法完成后的真实结果为准。</p></div>
        </aside>
      </main>
    </div>
  )
}
