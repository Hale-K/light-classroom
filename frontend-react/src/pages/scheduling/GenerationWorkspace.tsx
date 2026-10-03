import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import type { ScheduleEntry, SchedulingGridConfig, TeachingAssignment } from '@/types'
import type { GenStage, GenTraceEvent } from './scheduling-model'
import DigitalTwinMap from './DigitalTwinMap'

interface WorkspaceClass {
  id: number
  name: string
}
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
  subjects: Array<{ id: number; name: string }>
  calendar: ScheduleEntry[]
  gridConfig: SchedulingGridConfig
  academicYear: string
  term: string
  classes: WorkspaceClass[]
  selectedClassId?: number
  selectedClassName: string
  onClassChange: (classId: number) => void
  onClose: () => void
}
const SUBJECT_COLORS = ['blue', 'orange', 'green', 'violet', 'red', 'teal']
type Column = {
  label: string
  weekday: number
  parity: 'all' | 'odd' | 'even'
  code: string
}
type VisualRow = { type: 'day'; period: number } | { type: 'evening'; parity: 'odd' | 'even'; period: number }
function formatElapsed(seconds: number) {
  const value = Math.max(0, Math.floor(seconds))
  return `${Math.floor(value / 60)}分 ${String(value % 60).padStart(2, '0')}秒`
}
function parityMatches(entry: ScheduleEntry, column: Column, eveningParity?: 'odd' | 'even') {
  const entryParity = entry.week_parity || 'all'
  return (!eveningParity || entryParity === 'all' || entryParity === eveningParity) && (column.parity === 'all' || entryParity === 'all' || entryParity === column.parity)
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
  subjects,
  calendar,
  gridConfig,
  academicYear,
  term,
  classes,
  selectedClassId,
  selectedClassName,
  onClassChange,
  onClose,
}: GenerationWorkspaceProps) {
  const subjectQueue = useMemo(() => {
    const oddEvenIds = new Set([...(gridConfig.evening_subject_ids_odd || []), ...(gridConfig.evening_subject_ids_even || [])])
    const map = new Map<
      number,
      {
        id: number
        name: string
        count: number
        teacher?: string
        eveningOdd: boolean
        eveningEven: boolean
      }
    >()
    for (const subject of subjects) {
      if (subject.id > 0)
        map.set(subject.id, {
          id: subject.id,
          name: subject.name,
          count: 0,
          eveningOdd: oddEvenIds.has(subject.id) && (gridConfig.evening_subject_ids_odd || []).includes(subject.id),
          eveningEven: oddEvenIds.has(subject.id) && (gridConfig.evening_subject_ids_even || []).includes(subject.id),
        })
    }
    for (const item of assignments) {
      const current = map.get(item.subject_id)
      if (!current) continue
      if (item.weekly_periods > 0) current.count += item.weekly_periods
      if (item.teacher_name) current.teacher = current.teacher || item.teacher_name
    }
    return Array.from(map.values())
      .filter((subject) => subject.count > 0 || subject.eveningOdd || subject.eveningEven)
      .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, 'zh-CN'))
  }, [assignments, gridConfig.evening_subject_ids_even, gridConfig.evening_subject_ids_odd, subjects])
  const totalSlots = subjectQueue.reduce((sum, subject) => sum + subject.count, 0)
  const columns = useMemo<Column[]>(() => {
    const configuredDays = Math.min(7, Math.max(1, gridConfig.days || 5))
    const names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    const result: Column[] = []
    for (let weekday = 1; weekday <= configuredDays; weekday += 1) {
      if (weekday === 6 && gridConfig.enable_saturday) result.push({ label: '单六', weekday, parity: 'odd', code: 'sat-odd' }, { label: '双六', weekday, parity: 'even', code: 'sat-even' })
      else if (weekday !== 6 || !gridConfig.enable_saturday)
        result.push({
          label: names[weekday - 1],
          weekday,
          parity: 'all',
          code: `day-${weekday}`,
        })
    }
    return result
  }, [gridConfig.days, gridConfig.enable_saturday])
  const dayRows = Math.max(1, gridConfig.periods_per_day || 1)
  const visualRows = useMemo<VisualRow[]>(() => {
    const rows: VisualRow[] = Array.from({ length: dayRows }, (_, period) => ({
      type: 'day',
      period: period + 1,
    }))
    if (gridConfig.enable_evening) {
      const oddCount = Math.max(0, ...(gridConfig.evening_daily_periods_odd || []))
      const evenCount = Math.max(0, ...(gridConfig.evening_daily_periods_even || []))
      for (let index = 0; index < oddCount; index += 1) rows.push({ type: 'evening', parity: 'odd', period: index })
      for (let index = 0; index < evenCount; index += 1) rows.push({ type: 'evening', parity: 'even', period: index })
    }
    return rows
  }, [dayRows, gridConfig.enable_evening, gridConfig.evening_daily_periods_even, gridConfig.evening_daily_periods_odd])
  const previewCapacity = columns.length * visualRows.length
  const finalSlots = useMemo(() => {
    const findEntry = (column: Column, row: VisualRow) => {
      if (row.type === 'day') return calendar.find((item) => item.weekday === column.weekday && item.period === row.period && parityMatches(item, column))
      const start = gridConfig.evening_start_period || dayRows + 1
      return calendar.find((item) => item.weekday === column.weekday && item.period === start + row.period && parityMatches(item, column, row.parity))
    }
    return visualRows.flatMap((row) => columns.map((column) => findEntry(column, row)))
  }, [calendar, columns, dayRows, gridConfig.evening_start_period, visualRows])
  const dispatchTasks = useMemo(
    () =>
      finalSlots.flatMap((item, slotIndex) =>
        item?.subject_name
          ? [
              {
                slotIndex,
                item: {
                  subject_name: item.subject_name,
                  teacher_name: item.teacher_name,
                  preview: true,
                },
              },
            ]
          : [],
      ),
    [finalSlots],
  )
  const dispatchCapacity = dispatchTasks.length
  const [previewPlaced, setPreviewPlaced] = useState(0)
  const [robotCursor, setRobotCursor] = useState(0)
  const [robotPhase, setRobotPhase] = useState<'pickup' | 'moving' | 'drop'>('pickup')
  useEffect(() => {
    if (!open || generating) {
      setPreviewPlaced(0)
      setRobotCursor(0)
      setRobotPhase('pickup')
    }
  }, [generating, open])
  useEffect(() => {
    setPreviewPlaced(0)
    setRobotCursor(0)
    setRobotPhase('pickup')
  }, [selectedClassId])
  const dispatchReady = !generating && stage === 'done' && calendar.length > 0
  const playbackActive = dispatchReady && previewPlaced < dispatchCapacity
  const dispatchComplete = dispatchReady && previewPlaced >= dispatchCapacity
  useEffect(() => {
    if (!open || !playbackActive) return
    if (robotPhase === 'pickup' && previewPlaced >= dispatchCapacity) return
    const phaseDuration = robotPhase === 'pickup' ? 1800 : robotPhase === 'moving' ? 5400 : 1300
    const timer = window.setTimeout(() => {
      if (robotPhase === 'pickup') {
        setRobotPhase('moving')
        return
      }
      if (robotPhase === 'moving') {
        setRobotPhase('drop')
        return
      }
      setPreviewPlaced((value) => {
        if (value >= dispatchCapacity) return value
        const next = value + 1
        setRobotCursor(Math.min(next, Math.max(0, dispatchTasks.length - 1)))
        return next
      })
      setRobotPhase('pickup')
    }, phaseDuration)
    return () => window.clearTimeout(timer)
  }, [dispatchCapacity, dispatchTasks.length, open, playbackActive, previewPlaced, robotPhase])
  const displayedSlots = useMemo(() => {
    if (dispatchComplete) return finalSlots
    const slots = Array.from({ length: previewCapacity }, () => undefined as (typeof dispatchTasks)[number]['item'] | undefined)
    dispatchTasks.slice(0, previewPlaced).forEach((task) => {
      slots[task.slotIndex] = task.item
    })
    return slots
  }, [dispatchComplete, dispatchTasks, finalSlots, previewCapacity, previewPlaced])
  const dispatchPercent = dispatchCapacity > 0 ? Math.round((previewPlaced / dispatchCapacity) * 100) : 0
  const visiblePercent = generating ? Math.round(percent) : dispatchReady ? dispatchPercent : Math.round(percent)
  const workflowSteps: Array<{ label: string; state: 'pending' | 'current' | 'done' }> = [
    { label: '校验资源', state: stage === 'validating' ? 'current' : 'done' },
    {
      label: '完整求解',
      state: stage === 'generating' ? 'current' : stage === 'validating' ? 'pending' : 'done',
    },
    {
      label: '保存课表',
      state: stage === 'refreshing' ? 'current' : stage === 'done' ? 'done' : 'pending',
    },
    {
      label: '运输仿真',
      state: dispatchComplete ? 'done' : playbackActive ? 'current' : 'pending',
    },
  ]
  const placedCount = dispatchReady ? Math.min(previewPlaced, dispatchCapacity) : 0
  const activeDispatchTask = playbackActive ? dispatchTasks[Math.min(robotCursor, Math.max(0, dispatchTasks.length - 1))] : undefined
  const robotSlotIndex = activeDispatchTask?.slotIndex ?? 0
  const robotSubject = activeDispatchTask?.item
  const robotRouteColumn = robotSlotIndex % Math.max(1, columns.length)
  const robotRouteRow = Math.floor(robotSlotIndex / Math.max(1, columns.length))
  const robotRouteX = ((robotRouteColumn + 0.5) / Math.max(1, columns.length)) * 100
  const robotRouteY = ((robotRouteRow + 0.5) / Math.max(1, visualRows.length)) * 100
  const robotRoutePath = `M 0 50 L 5 50 L 5 ${robotRouteY} L ${robotRouteX} ${robotRouteY}`
  const robotMotion = robotPhase === 'pickup' ? { x: 0, y: 50 } : robotPhase === 'moving' ? { x: 5, y: robotRouteY } : { x: robotRouteX, y: robotRouteY }
  const robotStyle = {
    '--robot-col': robotSlotIndex % Math.max(1, columns.length),
    '--robot-row': Math.floor(robotSlotIndex / Math.max(1, columns.length)),
    '--robot-days': Math.max(1, columns.length),
    '--robot-x': robotMotion.x,
    '--robot-y': robotMotion.y,
  } as CSSProperties
  const robotPhaseLabel = robotPhase === 'pickup' ? '前往仓库取货' : robotPhase === 'moving' ? '沿通道运输' : '正在投递课位'
  const dispatchJobs = (
    playbackActive
      ? Array.from({ length: 3 }, (_, offset) => {
          const taskIndex = robotCursor + offset
          const task = dispatchTasks[taskIndex]
          const row = task ? visualRows[Math.floor(task.slotIndex / Math.max(1, columns.length))] : undefined
          const column = task ? columns[task.slotIndex % Math.max(1, columns.length)] : undefined
          return task && row && column
            ? {
                id: `JOB-${String(taskIndex + 1).padStart(3, '0')}`,
                subject: task.item.subject_name,
                target: row.type === 'day' ? `${column.label} · 第 ${row.period} 节` : `${column.label} · ${row.parity === 'odd' ? '单周' : '双周'}晚自习 ${row.period + 1}`,
                active: offset === 0,
              }
            : undefined
        }).filter(Boolean)
      : []
  ) as Array<{
    id: string
    subject: string
    target: string
    active: boolean
  }>
  if (!open) return null
  return (
    <div className="generation-workspace" role="dialog" aria-modal="true" aria-label="自动排课工作区">
      <header className="generation-workspace-header">
        <div className="generation-workspace-brand">
          <span className="generation-workspace-mark">排</span>
          <div>
            <strong>自动排课工作区</strong>
            <small>
              {academicYear} · 第 {term} 学期
            </small>
          </div>
        </div>
        <div className="generation-workspace-actions">
          <label className="generation-class-switch">
            当前班级
            <select value={selectedClassId ?? ''} onChange={(event) => onClassChange(Number(event.target.value))} disabled={generating || !classes.length}>
              <option value="" disabled>
                选择班级
              </option>
              {classes.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <span className={`generation-live-dot${generating || playbackActive ? ' is-live' : dispatchComplete ? ' is-done' : ''}`} />
          <span>{generating ? '正在生成完整课表' : playbackActive ? '课表已生成 · 配送中' : dispatchComplete ? '仿真完成' : '需要调整'}</span>
          <button type="button" onClick={onClose}>
            {generating || playbackActive ? '后台运行' : '返回排课管理'}
          </button>
        </div>
      </header>
      <main className="generation-workspace-body">
        <aside className="generation-subject-rail">
          <div className="generation-panel-title">
            <div>
              <span>SUBJECT QUEUE</span>
              <h2>{generating ? '等待最终课表' : playbackActive ? '配送学科' : '已排学科'}</h2>
            </div>
            <b>{subjectQueue.length}</b>
          </div>
          <p className="generation-panel-desc">{selectedClassName} · 左侧是学科仓库，机器人会取货后沿轨道搬运到指定课位。</p>
          <div className="generation-warehouse-badge">
            <span>▣</span>
            <strong>学科仓库</strong>
            <small>{generating ? '等待求解' : dispatchComplete ? '已完成' : robotPhase === 'pickup' ? '正在取货' : robotPhase === 'moving' ? '搬运中' : '正在放置'}</small>
          </div>
          <div className="generation-subject-list">
            {subjectQueue.map((subject, index) => {
              const previewCount = dispatchTasks.slice(0, previewPlaced).filter((task) => task.item.subject_name === subject.name).length
              const finalCount = calendar.filter((item) => item.subject_id === subject.id).length
              const subjectPlaced = dispatchComplete ? Math.min(subject.count, finalCount) : previewCount
              const isCarrying = robotSubject?.subject_name === subject.name
              return (
                <div
                  className={`generation-subject-card color-${SUBJECT_COLORS[index % SUBJECT_COLORS.length]}${isCarrying ? ' is-carrying' : subjectPlaced >= subject.count ? ' is-done' : subjectPlaced > 0 ? ' is-active' : ''}${subject.eveningOdd ? ' evening-odd' : ''}${subject.eveningEven ? ' evening-even' : ''}}`}
                  key={subject.id}
                >
                  <div className="generation-subject-icon">{subject.name.slice(0, 1)}</div>
                  <div className="generation-subject-copy">
                    <strong>{subject.name}</strong>
                    <small>
                      {subject.teacher || '教师待匹配'}
                      {subject.eveningOdd ? ' · 单周晚自习' : ''}
                      {subject.eveningEven ? ' · 双周晚自习' : ''}
                    </small>
                    <div className="generation-subject-progress">
                      <i
                        style={{
                          width: `${subject.count > 0 ? Math.round((subjectPlaced / subject.count) * 100) : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                  <em>{subject.count > 0 ? `${subjectPlaced}/${subject.count}` : '晚自习配置'}</em>
                </div>
              )
            })}
            {!subjectQueue.length && <div className="generation-empty">暂无可排学科，请先配置课时和任教关系。</div>}
          </div>
          <div className="generation-rail-footer">
            <span>{generating ? '等待配送' : dispatchComplete ? '已投递' : '配送进度'}</span>
            <strong>{placedCount}</strong>
            <small>/ {dispatchReady ? dispatchCapacity : totalSlots} 个课位</small>
          </div>
        </aside>
        <section className="generation-board">
          <div className="generation-board-head">
            <div>
              <span className="generation-eyebrow">ROBOT DISPATCH SIMULATION · DATABASE GRID</span>
              <h1>{generating ? '正在生成完整课表' : playbackActive ? '课表已生成，正在配送' : dispatchComplete ? '课表配送完成' : '排课未完成'}</h1>
              <p>{playbackActive ? `最终课表已经保存，正在将第 ${previewPlaced + 1} / ${dispatchCapacity} 个课程运输到真实课位。` : summary || '等待算法开始…'}</p>
            </div>
            <div className="generation-board-stat">
              <strong>{visiblePercent}%</strong>
              <small>{generating ? (solutions ? `${solutions} 个可行解` : '完整求解中') : playbackActive ? `${previewPlaced}/${dispatchCapacity} 个课位已投递` : dispatchComplete ? `${dispatchCapacity} 个课位配送完成` : '等待任务'}</small>
            </div>
          </div>
          <div className="generation-progress-track">
            <i style={{ width: `${Math.max(2, Math.min(100, visiblePercent))}%` }} />
          </div>
          <DigitalTwinMap
            columns={columns}
            rows={visualRows}
            items={displayedSlots}
            activeSlotIndex={robotSlotIndex}
            activeSubject={robotSubject?.subject_name}
            activeTeacher={robotSubject?.teacher_name}
            robotPhase={robotPhase}
            subjectNames={subjectQueue.map((subject) => subject.name)}
            playbackActive={playbackActive}
            isUnavailable={(column, row) =>
              row.type === 'day'
                ? row.period > (gridConfig.daily_periods?.[column.weekday - 1] ?? dayRows)
                : (column.parity !== 'all' && column.parity !== row.parity) ||
                  row.period >= (row.parity === 'odd' ? gridConfig.evening_daily_periods_odd?.[column.weekday - 1] || 0 : gridConfig.evening_daily_periods_even?.[column.weekday - 1] || 0)
            }
          />
          <div
            className={`generation-grid${playbackActive ? ' is-simulating' : ' is-result'}`}
            style={{
              gridTemplateColumns: `92px repeat(${columns.length}, minmax(100px, 1fr))`,
            }}
          >
            <div className="generation-grid-corner">课位 / 星期</div>
            {columns.map((column) => (
              <div className="generation-day" key={column.code}>
                <strong>{column.label}</strong>
                <small>{column.parity === 'all' ? `DAY ${String(column.weekday).padStart(2, '0')}` : column.parity === 'odd' ? 'ODD WEEK' : 'EVEN WEEK'}</small>
              </div>
            ))}
            {playbackActive && (
              <div className="generation-robot-track" aria-hidden="true">
                <svg viewBox={`0 0 100 ${Math.max(1, visualRows.length) * 100}`} preserveAspectRatio="none">
                  {visualRows.map((_, index) => (
                    <line key={`row-${index}`} x1="0" y1={`${(index + 0.5) * 100}`} x2="100" y2={`${(index + 0.5) * 100}`} />
                  ))}
                  {columns.map((_, index) => (
                    <line
                      key={`col-${index}`}
                      x1={`${((index + 0.5) / columns.length) * 100}`}
                      y1="0"
                      x2={`${((index + 0.5) / columns.length) * 100}`}
                      y2={`${Math.max(1, visualRows.length) * 100}`}
                    />
                  ))}
                  <path className="generation-route-path" d={robotRoutePath} pathLength="1" />
                  <circle className="generation-route-source" cx="0" cy="50" r="2.5" />
                  <circle className="generation-route-target" cx={robotRouteX} cy={robotRouteY} r="2.5" />
                </svg>
              </div>
            )}
            {playbackActive && robotSubject && (
              <div className={`generation-robot is-${robotPhase}`} key={`${previewPlaced}-${robotSubject.subject_name}`} style={robotStyle} aria-live="polite">
                <span className="generation-robot-icon">🤖</span>
                <span className="generation-robot-card">
                  <strong>{robotSubject.subject_name}</strong>
                  <small>
                    正在搬运至第{' '}
                    {visualRows[robotSlotIndex]?.type === 'day'
                      ? `${visualRows[robotSlotIndex].period} 节`
                      : `${visualRows[robotSlotIndex]?.parity === 'odd' ? '单周' : '双周'}晚自习 ${visualRows[robotSlotIndex]?.period + 1}`}{' '}
                    · {columns[robotSlotIndex % columns.length]?.label}
                  </small>
                </span>
              </div>
            )}
            {visualRows.map((row, rowIndex) => (
              <div className="generation-grid-row" key={`${row.type}-${row.type === 'day' ? row.period : `${row.parity}-${row.period}`}`}>
                <div className="generation-period">
                  {row.type === 'day' ? `第 ${row.period} 节` : `${row.parity === 'odd' ? '单周' : '双周'}`}
                  <small>{row.type === 'day' ? (row.period <= Math.ceil(dayRows / 2) ? '上午' : '下午') : '晚间'}</small>
                </div>
                {columns.map((column, columnIndex) => {
                  const item = displayedSlots[rowIndex * columns.length + columnIndex]
                  const color = item?.subject_name ? SUBJECT_COLORS[(subjectQueue.findIndex((subject) => subject.name === item.subject_name?.split(' · ')[0]) + 6) % 6] : ''
                  const unavailable =
                    row.type === 'day'
                      ? row.period > (gridConfig.daily_periods?.[column.weekday - 1] ?? dayRows)
                      : (column.parity !== 'all' && column.parity !== row.parity) ||
                        row.period >= (row.parity === 'odd' ? gridConfig.evening_daily_periods_odd?.[column.weekday - 1] || 0 : gridConfig.evening_daily_periods_even?.[column.weekday - 1] || 0)
                  return (
                    <div
                      className={`generation-slot ${item ? 'has-subject' : ''} ${item && 'preview' in item && item.preview ? 'is-preview' : ''} ${unavailable ? 'is-unavailable' : ''} color-${color}`}
                      key={column.code}
                    >
                      {item ? (
                        <>
                          <strong>{item.subject_name}</strong>
                          <small>{item.teacher_name || '自动匹配教师'}</small>
                        </>
                      ) : (
                        <span>{unavailable ? '不可排' : '等待课位'}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
          <div className="generation-board-foot">
            <span>
              <i className="legend live" />
              正在放置
            </span>
            <span>
              <i className="legend final" />
              已确认课位
            </span>
            <span>
              <i className="legend empty" />
              待计算
            </span>
            <span className="generation-clock">已用时 {formatElapsed(elapsed)}</span>
          </div>
        </section>
        <aside className="generation-inspector">
          <div className="generation-panel-title">
            <div>
              <span>TRANSPORT JOBS</span>
              <h2>机器人调度</h2>
            </div>
            {(generating || playbackActive) && <span className="generation-spinner" />}
          </div>
          <div className="generation-dispatch-current">
            <div>
              <span className="generation-agv-id">AGV-01</span>
              <small>{playbackActive ? robotPhaseLabel : '待命区'}</small>
            </div>
            <strong>{robotSubject?.subject_name || (dispatchComplete ? '本轮调度已完成' : generating ? '等待最终课表' : '等待调度任务')}</strong>
            <p>{dispatchJobs[0]?.target || (dispatchComplete ? `已完成 ${placedCount} 个课位投递` : generating ? '完整课表生成并保存后开始配送' : '正在准备运输任务')}</p>
          </div>
          {dispatchJobs.length > 0 && (
            <div className="generation-job-list" aria-label="运输任务队列">
              {dispatchJobs.map((job) => (
                <div className={`generation-job-card${job.active ? ' is-active' : ''}`} key={job.id}>
                  <div>
                    <strong>{job.id}</strong>
                    <small>{job.active ? robotPhaseLabel : '等待分配'}</small>
                  </div>
                  <p>
                    <span>{job.subject}</span>
                    <i>→</i>
                    <span>{job.target}</span>
                  </p>
                </div>
              ))}
            </div>
          )}
          <ol className="generation-stage-list">
            {workflowSteps.map((item, index) => (
              <li className={item.state === 'done' ? 'is-done' : item.state === 'current' ? 'is-current' : ''} key={item.label}>
                <i>{item.state === 'done' ? '✓' : index + 1}</i>
                <span>{item.label}</span>
              </li>
            ))}
          </ol>
          <div className="generation-message">
            <strong>{generating ? '算法正在生成完整课表' : playbackActive ? '最终课表已保存，机器人正在配送' : dispatchComplete ? '全部课位配送完成' : '排课任务需要处理'}</strong>
            <p>{playbackActive ? `正在执行 JOB-${String(robotCursor + 1).padStart(3, '0')}，剩余 ${Math.max(0, dispatchCapacity - previewPlaced)} 个课位。` : summary || '正在等待任务状态…'}</p>
          </div>
          <div className="generation-trace">
            <div className="generation-trace-title">
              最近事件 <small>{trace.length}</small>
            </div>
            {trace
              .slice(-5)
              .reverse()
              .map((event, index) => (
                <div className="generation-trace-item" key={`${event.message}-${index}`}>
                  <i />
                  {event.message || '状态已更新'}
                </div>
              ))}
          </div>
          <div className="generation-inspector-note">
            <strong>提示</strong>
            <p>课表网格来自数据库课位结构；单六、双六和单双周晚自习均按真实配置展示。</p>
          </div>
        </aside>
      </main>
    </div>
  )
}
