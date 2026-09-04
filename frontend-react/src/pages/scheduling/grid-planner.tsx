import { useEffect, useMemo, useState } from 'react'
import { App, Button, Select, Space, Tag, Tooltip } from 'antd'
import { SaveOutlined, ThunderboltOutlined, UndoOutlined } from '@ant-design/icons'
import type { ClassInfo, SchedulingGridConfig, SubjectInfo, TeachingAssignment } from '@/types'

import './grid-planner.css'

type SlotKind = 'day' | 'evening'
type CellSource = 'manual' | 'auto'

interface PlannerCell {
  subject_id: number
  teacher_id?: number | null
  assignment_id?: number
  source: CellSource
}

interface PreviewScheduleItem {
  assignment_id: number
  class_id: number
  weekday: number
  period: number
  subject_id: number
  teacher_id: number | null
}

interface Props {
  classes: ClassInfo[]
  subjects: SubjectInfo[]
  assignments: TeachingAssignment[]
  selectedClassId?: number
  academicYear: string
  term: string
  gridConfig: SchedulingGridConfig
  onAutoArrange: (lockedItems: Array<{
    assignment_id?: number
    class_id: number
    subject_id: number
    teacher_id?: number | null
    weekday: number
    period: number
  }>) => Promise<PreviewScheduleItem[]>
}

const DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const clampDays = (value: number) => Math.min(7, Math.max(1, value || 1))
const clampRows = (value: number) => Math.min(12, Math.max(1, value || 1))
const cellKey = (day: number, row: number) => `${day}-${row}`

export default function GridPlanner({
  classes,
  subjects,
  assignments,
  selectedClassId,
  academicYear,
  term,
  gridConfig,
  onAutoArrange,
}: Props) {
  const { message } = App.useApp()
  // 课位结构只从后端配置读取，预排工作台不再维护自己的矩阵尺寸或课位类型。
  const dailyPeriods = Array.from({ length: 7 }, (_, index) => gridConfig.daily_periods[index] ?? 0)
  const eveningPeriodsOdd = Array.from({ length: 7 }, (_, index) => gridConfig.evening_daily_periods_odd[index] ?? 0)
  const eveningPeriodsEven = Array.from({ length: 7 }, (_, index) => gridConfig.evening_daily_periods_even[index] ?? 0)
  const eveningPeriods = eveningPeriodsOdd.map((count, index) => Math.max(count, eveningPeriodsEven[index]))
  const days = clampDays(gridConfig.days)
  const dayRows = clampRows(gridConfig.periods_per_day)
  const eveningRows = gridConfig.enable_evening ? Math.max(...eveningPeriods, 0) : 0
  const rows = dayRows + eveningRows
  const [cells, setCells] = useState<Record<string, PlannerCell>>({})
  const [hydratedKey, setHydratedKey] = useState('')
  const [autoArranging, setAutoArranging] = useState(false)

  const selectedClass = classes.find((item) => item.id === selectedClassId)
  const classAssignments = useMemo(
      () => assignments
        .filter((item) => item.class_id === selectedClassId && item.academic_year === academicYear && item.term === term)
        .filter((item) => item.subject_id > 0 && item.weekly_periods > 0),
    [academicYear, assignments, selectedClassId, term],
  )

  const subjectMap = useMemo(() => new Map(subjects.map((item) => [item.id, item])), [subjects])
  const teacherMap = useMemo(() => {
    const map = new Map<number, string>()
    for (const assignment of classAssignments) {
      if (assignment.teacher_id && assignment.teacher_name) map.set(assignment.teacher_id, assignment.teacher_name)
    }
    return map
  }, [classAssignments])
  const assignmentBySubject = useMemo(() => {
    const map = new Map<number, TeachingAssignment>()
    for (const assignment of classAssignments) {
      if (!map.has(assignment.subject_id)) map.set(assignment.subject_id, assignment)
    }
    return map
  }, [classAssignments])
  const courseOptions = useMemo(() => {
    const seen = new Set<number>()
    return classAssignments
      .filter((assignment) => {
        if (seen.has(assignment.subject_id)) return false
        seen.add(assignment.subject_id)
        return true
      })
      .sort((left, right) => (left.subject_name || '').localeCompare(right.subject_name || '', 'zh-CN'))
      .map((assignment) => ({
        value: assignment.subject_id,
        label: `${assignment.subject_name || subjectMap.get(assignment.subject_id)?.name || '未命名学科'}${assignment.teacher_name ? ` · ${assignment.teacher_name}` : ''}`,
      }))
  }, [classAssignments, subjectMap])

  // 矩阵从单一行数升级为白天/晚上两组行数，切换版本避免旧缓存把晚课恢复成白课。
  const structureSignature = `${days}:${dailyPeriods.join(',')}:${eveningPeriodsOdd.join(',')}:${eveningPeriodsEven.join(',')}`
  const storageKey = `scheduling.grid-planner.v3.${selectedClassId || 'none'}.${academicYear}.${term}.${structureSignature}`
  const slotKindAtRow = (row: number): SlotKind => row >= dayRows ? 'evening' : 'day'
  const isSlotAvailable = (day: number, row: number) => {
    if (row < dayRows) return row < (dailyPeriods[day - 1] ?? 0)
    return row - dayRows < (eveningPeriods[day - 1] ?? 0)
  }
  const visibleCells = useMemo(
    () => Object.entries(cells).filter(([key]) => {
      const [day, row] = key.split('-').map(Number)
      return day >= 1 && day <= days && row >= 0 && row < rows && isSlotAvailable(day, row)
    }),
    [cells, days, rows, dailyPeriods, eveningPeriods],
  )
  const fixedCount = visibleCells.filter(([, cell]) => cell.source === 'manual').length
  const autoCount = visibleCells.filter(([, cell]) => cell.source === 'auto').length
  const availableSlotCount = dailyPeriods.slice(0, days).reduce((sum, count) => sum + count, 0)
    + eveningPeriods.slice(0, days).reduce((sum, count) => sum + count, 0)
  const emptyCount = Math.max(0, availableSlotCount - visibleCells.length)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey)
      const parsed = raw ? JSON.parse(raw) as { cells?: Record<string, PlannerCell> } : undefined
      setCells(parsed?.cells || {})
    } catch {
      setCells({})
    }
    setHydratedKey(storageKey)
  }, [storageKey])

  useEffect(() => {
    if (hydratedKey !== storageKey) return
    try {
      localStorage.setItem(storageKey, JSON.stringify({ cells }))
    } catch {
      // 本地预排方案保存失败时不影响当前编辑。
    }
  }, [cells, hydratedKey, storageKey])

  const updateCell = (day: number, row: number, subjectId?: number) => {
    if (!isSlotAvailable(day, row)) return
    const key = cellKey(day, row)
    if (!subjectId) {
      setCells((current) => {
        const next = { ...current }
        delete next[key]
        return next
      })
      return
    }
    const assignment = assignmentBySubject.get(subjectId)
    setCells((current) => ({
      ...current,
      [key]: {
        subject_id: subjectId,
        teacher_id: assignment?.teacher_id,
        assignment_id: assignment?.id,
        source: 'manual',
      },
    }))
  }

  const clearAutomaticCells = () => {
    setCells((current) => Object.fromEntries(Object.entries(current).filter(([, cell]) => cell.source === 'manual')))
  }

  const clearAllCells = () => {
    setCells({})
    message.info('已清空预排网格，课时和正式课表数据未改变')
  }

  const automaticSchedule = async () => {
    if (!selectedClassId) {
      message.warning('请先选择班级')
      return
    }
    if (!classAssignments.length) {
      message.warning('当前班级暂无任教关系，无法自动编排')
      return
    }

    const lockedItems = Object.entries(cells)
      // 晚课由后端按单双周和晚课配置统一生成；网格只把白天的锁定课位交给引擎。
      .filter(([key, cell]) => cell.source === 'manual' && Number(key.split('-')[1]) < dayRows)
      .map(([key, cell]) => {
        const [day, row] = key.split('-').map(Number)
        return {
          assignment_id: cell.assignment_id,
          class_id: selectedClassId,
          subject_id: cell.subject_id,
          teacher_id: cell.teacher_id,
          weekday: day,
          period: row + 1,
        }
      })
    try {
      const previewItems = await onAutoArrange(lockedItems)
      const next: Record<string, PlannerCell> = Object.fromEntries(
        Object.entries(cells).filter(([, cell]) => cell.source === 'manual'),
      )
      for (const item of previewItems) {
        const row = item.period <= dayRows
          ? item.period - 1
          : gridConfig.evening_start_period != null
            ? dayRows + item.period - gridConfig.evening_start_period
            : -1
        if (row < 0 || !isSlotAvailable(item.weekday, row)) continue
        const key = cellKey(item.weekday, row)
        if (next[key]) continue
        next[key] = {
          subject_id: item.subject_id,
          teacher_id: item.teacher_id,
          assignment_id: item.assignment_id,
          source: 'auto',
        }
      }
      const placed = Object.values(next).filter((cell) => cell.source === 'auto').length
      setCells(next)
      message.success(`已生成 ${placed} 个后端校验通过的建议课位，${fixedCount} 个固定课位保持不动`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '自动编排失败，请先检查课时、任教关系和规则')
    } finally {
      setAutoArranging(false)
    }
  }

  const savePlan = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ cells }))
      setHydratedKey(storageKey)
      message.success('预排网格已保存，可继续调整后执行自动编排')
    } catch {
      message.error('预排网格保存失败')
    }
  }

  return (
    <section className="grid-planner">
      <div className="grid-planner-head">
        <div>
          <div className="grid-planner-kicker"><span /> GRID PLANNER / 预排工作台</div>
          <h2>先摆好骨架，再保存预排</h2>
          <p>固定课位会被保留；自动编排由后端按课时、教师和规则校验后生成建议。</p>
        </div>
        <div className="grid-planner-head-actions">
          <Button icon={<UndoOutlined />} onClick={clearAutomaticCells}>清除自动课</Button>
          <Button icon={<SaveOutlined />} onClick={savePlan}>保存预排</Button>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={autoArranging} disabled={autoArranging} onClick={() => void automaticSchedule()}>自动编排</Button>
        </div>
      </div>

      <div className="grid-planner-meta">
        <div className="grid-planner-class">
          <span className="grid-planner-label">当前班级</span>
          <strong>{selectedClass?.name || '未选择班级'}</strong>
          {selectedClass?.cohort_label && <Tag color="blue">{selectedClass.cohort_label}届</Tag>}
        </div>
      </div>

      <div className="grid-planner-stats">
        <div><span className="stat-dot fixed" /><strong>{fixedCount}</strong><small>固定课位</small></div>
        <div><span className="stat-dot auto" /><strong>{autoCount}</strong><small>自动课位</small></div>
        <div><span className="stat-dot empty" /><strong>{emptyCount}</strong><small>空课位</small></div>
      </div>

      <div className="grid-planner-workspace">
        <aside className="grid-planner-tree">
          <div className="planner-tree-head">
            <span className="tree-icon">⌘</span>
            <div><strong>时段树</strong><small>{days} 天 · {availableSlotCount} 个可排课位</small></div>
          </div>
          <div className="planner-tree-groups">
            <div className="planner-tree-group">
              <div className="planner-tree-group-title"><span>▾</span> 正式课位 <em>{dayRows} 节</em></div>
              {Array.from({ length: dayRows }, (_, row) => row).map((row) => (
                <div className="planner-tree-node" key={row}>
                  <span className="tree-branch">├</span>
                  <span className="tree-node-name">第 {row + 1} 节</span>
                  <span className="tree-node-kind">正式课</span>
                </div>
              ))}
            </div>
            {eveningRows > 0 && <div className="planner-tree-group evening">
              <div className="planner-tree-group-title"><span>▾</span> 特殊课位 <em>{eveningRows} 节</em></div>
              {Array.from({ length: eveningRows }, (_, index) => index + dayRows).map((row) => (
                <div className="planner-tree-node" key={row}>
                  <span className="tree-branch">├</span>
                  <span className="tree-node-name">第 {row + 1} 节</span>
                  <span className="tree-node-kind evening">特殊课位</span>
                </div>
              ))}
            </div>}
          </div>
          <div className="planner-tree-foot"><span /> 课位类型与数量来自“课位结构”配置</div>
        </aside>

        <div className="grid-planner-grid-wrap">
          <div className="grid-planner-grid" style={{ gridTemplateColumns: `132px repeat(${days}, minmax(138px, 1fr))` }}>
            <div className="planner-corner"><span>PERIODS</span><strong>课位安排</strong></div>
            {DAY_NAMES.slice(0, days).map((day, index) => (
              <div className="planner-day-head" key={day}>
                <strong>{day}</strong>
                <small>DAY {String(index + 1).padStart(2, '0')}</small>
              </div>
            ))}
            {Array.from({ length: rows }, (_, row) => (
              <div className="planner-grid-row" key={row}>
                <div className={`planner-period-head ${slotKindAtRow(row) === 'evening' ? 'is-evening' : ''}`}>
                  <span className="planner-period-number">{String(row + 1).padStart(2, '0')}</span>
                  <div><strong>第 {row + 1} 节</strong><small>{slotKindAtRow(row) === 'evening' ? '特殊课位 · SPECIAL' : '正式课位 · FORMAL'}</small></div>
                </div>
                {Array.from({ length: days }, (_, dayIndex) => {
                  const day = dayIndex + 1
                  const cell = cells[cellKey(day, row)]
                  const slotAvailable = isSlotAvailable(day, row)
                  const subject = cell ? subjectMap.get(cell.subject_id) : undefined
                  const teacherName = cell?.teacher_id ? teacherMap.get(cell.teacher_id) : assignmentBySubject.get(cell?.subject_id || 0)?.teacher_name
                  return (
                    <div className={`planner-cell ${!slotAvailable ? 'is-unavailable' : ''} ${cell?.source === 'manual' ? 'is-fixed' : ''} ${cell?.source === 'auto' ? 'is-auto' : ''}`} key={day}>
                      <div className="planner-cell-topline">
                        <span className="cell-index">{String(day).padStart(2, '0')} / {String(row + 1).padStart(2, '0')}</span>
                        {cell && <span className={`cell-source ${cell.source}`}>{cell.source === 'manual' ? '锁定' : '自动'}</span>}
                      </div>
                      {slotAvailable ? <Select
                        className="planner-cell-select"
                        size="middle"
                        allowClear
                        showSearch
                        optionFilterProp="label"
                        value={cell?.subject_id}
                        placeholder="点击设置课程"
                        options={courseOptions}
                        onChange={(value: number | undefined) => updateCell(day, row, value)}
                      /> : <span className="planner-unavailable-label">未开放</span>}
                      {cell && (
                        <div className="planner-cell-detail">
                          <span>{teacherName || '待配置坐班老师'}</span>
                          <Tooltip title={cell.source === 'manual' ? '固定课位：自动编排时不会移动' : '自动课位：可清除'}>
                            <span className="planner-lock">{cell.source === 'manual' ? '◆' : '◇'}</span>
                          </Tooltip>
                        </div>
                      )}
                      {!cell && slotAvailable && <span className="planner-empty-hint">留给算法或手动安排</span>}
                      {subject?.evening_study_allowed && slotKindAtRow(row) === 'evening' && <span className="planner-evening-mark">特殊课位可排</span>}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
          <div className="planner-grid-footer">
            <Space size={18}>
              <span><i className="legend-dot fixed" />固定课位</span>
              <span><i className="legend-dot auto" />自动填充</span>
              <span><i className="legend-dot empty" />空课位</span>
            </Space>
            <Button type="text" danger size="small" onClick={clearAllCells}>清空全部预排</Button>
          </div>
        </div>
      </div>
    </section>
  )
}
