import { useEffect, useMemo, useState } from 'react'
import {
  DndContext,
  PointerSensor,
  TouchSensor,
  KeyboardSensor,
  closestCorners,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core'
import type { DragEndEvent } from '@dnd-kit/core'
import { App, Button, Input, InputNumber, Modal, Select, Spin, Table, Tabs, Tag } from 'antd'
import { orgApi, seatingApi } from '@/api'
import type { ClassInfo, SeatArrangement, SeatEntry, Student } from '@/types'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import './index.css'

/** 排序方式维度：决定学生入座顺序 */
const ORDER_OPTIONS = [
  {
    value: 'roster',
    label: '按名册顺序',
    desc: '按学生名册序号从前到后依次入座',
  },
  {
    value: 'gender',
    label: '男女交错',
    desc: '前后同性别轮流就座，人数允许时尽量交替安排',
  },
  {
    value: 'random',
    label: '随机排列',
    desc: '使用固定种子生成可复现的随机顺序',
  },

]

/** 排布方式维度：决定顺序如何填入座位矩阵 */
const LAYOUT_OPTIONS = [
  {
    value: 'normal',
    label: '逐行顺排',
    desc: '每行从左到右顺序填充',
  },
  {
    value: 'snake',
    label: '蛇形排列',
    desc: '相邻两行方向相反，便于连续点名',
  },
]

/** 搭配方式维度：决定同桌间的搭配逻辑 */
const PAIRING_OPTIONS = [
  {
    value: 'none',
    label: '不搭配',
    desc: '按排序顺序直接入座，不做同桌搭配',
  },
  {
    value: 'height',
    label: '身高互补',
    desc: '一高一矮交替安排在相邻座位，便于相互照应',
  },
]

const ORDER_LABEL: Record<string, string> = Object.fromEntries(
  ORDER_OPTIONS.map((o) => [o.value, o.label]),
)
const LAYOUT_LABEL: Record<string, string> = Object.fromEntries(
  LAYOUT_OPTIONS.map((o) => [o.value, o.label]),
)
const PAIRING_LABEL: Record<string, string> = Object.fromEntries(
  PAIRING_OPTIONS.map((o) => [o.value, o.label]),
)

export interface RuleTemplate {
  /** 模板唯一 id（用于前端选中态） */
  id: string
  /** 模板名称 */
  label: string
  /** 模板说明 */
  desc: string
  icon: string
  color: string
  /** 排序方式（order 维度） */
  order: string
  /** 排布方式（layout 维度） */
  layout: string
  /** 搭配方式（pairing 维度） */
  pairing: string
}

const dimLabel = (order: string, layout: string, pairing = 'none') =>
  `${ORDER_LABEL[order] || order} · ${LAYOUT_LABEL[layout] || layout}${
    pairing && pairing !== 'none' ? ` · ${PAIRING_LABEL[pairing] || pairing}` : ''
  }`

/** 内置模板：由「排序方式 × 排布方式 × 搭配方式」多维叠加而成 */
const DEFAULT_TEMPLATES: RuleTemplate[] = [
  { id: 'roster-normal', label: '名册座次', order: 'roster', layout: 'normal', pairing: 'none', desc: dimLabel('roster', 'normal'), icon: 'list', color: '#3b82f6' },
  { id: 'roster-snake', label: '蛇形点名', order: 'roster', layout: 'snake', pairing: 'none', desc: dimLabel('roster', 'snake'), icon: 'git-branch', color: '#8b5cf6' },
  { id: 'gender-normal', label: '男女交错', order: 'gender', layout: 'normal', pairing: 'none', desc: dimLabel('gender', 'normal'), icon: 'users', color: '#ec4899' },
  { id: 'gender-snake', label: '交错蛇形', order: 'gender', layout: 'snake', pairing: 'none', desc: dimLabel('gender', 'snake'), icon: 'users', color: '#ef4444' },
  { id: 'random-normal', label: '随机换座', order: 'random', layout: 'normal', pairing: 'none', desc: dimLabel('random', 'normal'), icon: 'shuffle', color: '#f59e0b' },
  { id: 'height-combo', label: '身高互补', order: 'roster', layout: 'normal', pairing: 'height', desc: dimLabel('roster', 'normal', 'height'), icon: 'users', color: '#10b981' },
]

const RULE_PAGE_SIZE = 4
const DEFAULT_KEY = 'seating-default-rule'

const STATUS_LABEL: Record<string, string> = {
  active: '使用中',
  archived: '已归档',
  draft: '草稿',
}

/** 学生配对编辑：从班级名册选择两人组成一对，支持增删，用于隔离/挨着她坐约束 */
function StudentPairField({
  students,
  pairs,
  onChange,
  aPlaceholder = '选择甲',
  bPlaceholder = '选择乙',
}: {
  students: Student[]
  pairs: number[][]
  onChange: (pairs: number[][]) => void
  aPlaceholder?: string
  bPlaceholder?: string
}) {
  const [aId, setAId] = useState<number>()
  const [bId, setBId] = useState<number>()
  const nameOf = (id: number) => students.find((s) => s.id === id)?.name || `学生${id}`
  const addPair = () => {
    if (aId == null || bId == null || aId === bId) return
    if (pairs.some((p) => p.includes(aId) && p.includes(bId))) return
    onChange([...pairs, [aId, bId]])
    setAId(undefined)
    setBId(undefined)
  }
  const removePair = (idx: number) => onChange(pairs.filter((_, i) => i !== idx))
  const opts = students.map((s) => ({ label: s.name, value: s.id }))
  return (
    <div className="st-pair-field">
      <div className="st-pair-list">
        {pairs.length === 0 ? (
          <span className="st-pair-empty">尚未设置</span>
        ) : (
          pairs.map((p, idx) => (
            <span key={idx} className="st-pair-tag">
              {nameOf(p[0])} ↔ {nameOf(p[1])}
              <button
                type="button"
                className="st-pair-remove"
                onClick={() => removePair(idx)}
                aria-label="移除该对学生"
              >
                ×
              </button>
            </span>
          ))
        )}
      </div>
      <div className="st-pair-add">
        <Select
          size="small"
          placeholder={aPlaceholder}
          value={aId}
          onChange={setAId}
          showSearch
          optionFilterProp="label"
          options={opts}
        />
        <span className="st-pair-sep">与</span>
        <Select
          size="small"
          placeholder={bPlaceholder}
          value={bId}
          onChange={setBId}
          showSearch
          optionFilterProp="label"
          disabled={aId == null}
          options={opts.filter((o) => o.value !== aId)}
        />
        <Button
          size="small"
          type="link"
          icon={<Icon name="plus" size={13} />}
          disabled={aId == null || bId == null}
          onClick={addPair}
        >
          添加
        </Button>
      </div>
    </div>
  )
}

/** 单个座位格：有学生时可拖拽，任意格都是放置目标 */
function SeatCell({
  row,
  col,
  seat,
  activeId,
}: {
  row: number
  col: number
  seat?: SeatEntry
  activeId?: string
}) {
  const cellId = `${row}-${col}`
  const { setNodeRef: setDroppableRef, isOver } = useDroppable({ id: cellId })
  const {
    attributes,
    listeners,
    setNodeRef: setDraggableRef,
    isDragging,
    transform,
  } = useDraggable({ id: cellId })

  const setCellRef = (node: HTMLDivElement | null) => {
    setDroppableRef(node)
    setDraggableRef(node)
  }

  const isActive = activeId === cellId

  return (
    <div
      ref={setCellRef}
      className={[
        'st-seat',
        seat ? '' : 'empty',
        isOver && seat ? 'drop-ok' : '',
        isActive && isDragging ? 'dragging' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      style={
        transform && isDragging
          ? {
              transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
              zIndex: 3,
            }
          : undefined
      }
      {...attributes}
      {...(seat ? listeners : {})}
    >
      {seat ? (
        <>
          <span className="st-seat-no">
            {row}-{col}
          </span>
          <strong>{seat.student_name}</strong>
          <small>{seat.student_no || '未录学号'}</small>
        </>
      ) : (
        <span className="st-empty-text">空位</span>
      )}
    </div>
  )
}

export default function SeatingView() {
  const { message, modal } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [classes, setClasses] = useState<ClassInfo[]>([])
  const [arrangements, setArrangements] = useState<SeatArrangement[]>([])
  /** 预览/可手动调整的工作座位（与 current 同步，拖拽后独立于后端） */
  const [workingSeats, setWorkingSeats] = useState<SeatEntry[]>([])
  const [dirty, setDirty] = useState(false)
  /** 正在拖拽的座位 key（row-col），用于拖拽高亮 */
  const [activeId, setActiveId] = useState<string>()
  const [students, setStudents] = useState<Student[]>([])
  const [selectedClassId, setSelectedClassId] = useState<number>()
  const [selectedArrangementId, setSelectedArrangementId] = useState<number>()
  const [rows, setRows] = useState(7)
  const [cols, setCols] = useState(6)
  const [templates, setTemplates] = useState<RuleTemplate[]>(DEFAULT_TEMPLATES)
  const [defaultTemplateId, setDefaultTemplateId] = useState<string>(
    () => localStorage.getItem(DEFAULT_KEY) || 'roster-normal',
  )
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>(defaultTemplateId)
  const [editTemplateId, setEditTemplateId] = useState<string | undefined>()
  const [ruleName, setRuleName] = useState('')
  const [ruleDesc, setRuleDesc] = useState('')
  const [ruleOrder, setRuleOrder] = useState('roster')
  const [ruleLayout, setRuleLayout] = useState('normal')
  const [rulePairing, setRulePairing] = useState('none')
  const [ruleModalOpen, setRuleModalOpen] = useState(false)
  const [frontIds, setFrontIds] = useState<number[]>([])
  /** 需隔离的学生对（ID 对：彼此不得相邻） */
  const [separationPairs, setSeparationPairs] = useState<number[][]>([])
  /** 想挨着坐的学生对（ID 对：尽量相邻） */
  const [adjacencyPairs, setAdjacencyPairs] = useState<number[][]>([])
  const [activeTab, setActiveTab] = useState<'rules' | 'seats'>('rules')

  const selectedRule = templates.find((t) => t.id === selectedTemplateId)

  const current = useMemo(
    () =>
      arrangements.find((item) => item.id === selectedArrangementId) ?? arrangements[0],
    [arrangements, selectedArrangementId],
  )
  const className =
    classes.find((item) => item.id === selectedClassId)?.name || '请选择班级'
  const capacity = rows * cols
  const ruleLabel = current
    ? dimLabel(current.rule, current.layout)
    : ''

  const seatAt = (row: number, col: number): SeatEntry | undefined =>
    workingSeats.find((seat) => seat.row === row && seat.col === col)

  // 切到某个座位方案时，工作座位随之同步
  useEffect(() => {
    setWorkingSeats(current?.seats ?? [])
    setDirty(false)
    setActiveId(undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, current?.seats])

  /** 将 source 位置的学生移动到 target 位置（target 为空） */
  const moveSeatTo = (source: SeatEntry, targetRow: number, targetCol: number) => {
    setWorkingSeats((prev) =>
      prev.map((seat) =>
        seat.row === source.row && seat.col === source.col
          ? { ...seat, row: targetRow, col: targetCol }
          : seat,
      ),
    )
    setDirty(true)
  }

  /** 交换两个占位座位的学生 */
  const swapSeats = (from: SeatEntry, to: SeatEntry) => {
    if (from.student_id === to.student_id) return
    setWorkingSeats((prev) =>
      prev.map((seat) => {
        if (seat.row === from.row && seat.col === from.col) {
          return { ...to, row: from.row, col: from.col }
        }
        if (seat.row === to.row && seat.col === to.col) {
          return { ...from, row: to.row, col: to.col }
        }
        return seat
      }),
    )
    setDirty(true)
  }

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setActiveId(undefined)
    const overId = over?.id
    if (overId == null || overId === active.id) return
    const [fromRow, fromCol] = String(active.id).split('-').map(Number)
    const [toRow, toCol] = String(overId).split('-').map(Number)
    const source = seatAt(fromRow, fromCol)
    const target = seatAt(toRow, toCol)
    if (!source) return
    if (target) {
      swapSeats(source, target)
    } else {
      moveSeatTo(source, toRow, toCol)
    }
  }

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 150, tolerance: 6 },
    }),
    useSensor(KeyboardSensor),
  )

  const saveSeats = async () => {
    if (!current || !dirty) return
    setLoading(true)
    try {
      // 后端契约：座位只接受 { row, col, student_id } 纯数字字段；
      // 带上 student_name/gender 等附加字段会触发 422 校验错误（每字段一条）
      const payload = workingSeats.map((s) => ({ row: s.row, col: s.col, student_id: s.student_id }))
      const item = await seatingApi.updateSeats(current.id, payload)
      setArrangements((prev) => prev.map((a) => (a.id === item.id ? item : a)))
      setWorkingSeats(item.seats)
      setDirty(false)
      message.success('座位调整已保存')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const loadArrangements = async () => {
    if (!selectedClassId) return
    setLoading(true)
    try {
      const data = await seatingApi.list(selectedClassId)
      setArrangements(data)
      setSelectedArrangementId(
        data.find((item) => item.status === 'active')?.id ?? data[0]?.id,
      )
    } catch (e) {
      message.error(e instanceof Error ? e.message : '座位表加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadStudents = async () => {
    if (!selectedClassId) return
    const data = await orgApi.students(selectedClassId)
    setStudents(data)
    setFrontIds((prev) => prev.filter((id) => data.some((s) => s.id === id)))
  }

  useEffect(() => {
    orgApi
      .classes()
      .then((data) => {
        setClasses(data)
        setSelectedClassId((prev) => prev ?? data[0]?.id)
      })
      .catch((e) => message.error(e instanceof Error ? e.message : '班级加载失败'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedClassId) return
    void Promise.all([loadArrangements(), loadStudents()])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClassId])

  const generate = async () => {
    if (!selectedClassId) {
      message.warning('请先选择班级')
      return
    }
    if (!selectedRule) {
      message.warning('请先在"建立规则"中选择一个规则模板')
      return
    }
    setLoading(true)
    try {
      const item = await seatingApi.generate({
        class_id: selectedClassId,
        rows,
        cols,
        order: selectedRule.order,
        layout: selectedRule.layout,
        pairing: selectedRule.pairing,
        seed: selectedRule.order === 'random' ? Date.now() : undefined,
        front_student_ids: frontIds,
        separation_pairs: separationPairs,
        adjacency_pairs: adjacencyPairs,
      })
      setArrangements((prev) => [item, ...prev])
      setSelectedArrangementId(item.id)
      setActiveTab('seats')
      message.success('新座位表已生成，确认后可启用')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '生成座位表失败')
    } finally {
      setLoading(false)
    }
  }

  const activate = async () => {
    if (!current || current.status === 'active') return
    modal.confirm({
      title: '启用座位表',
      content: '启用后，当前正在使用的座位表会自动归档。',
      okText: '确认启用',
      okButtonProps: { danger: true },
      onOk: async () => {
        await seatingApi.activate(current.id)
        await loadArrangements()
        message.success('座位表已启用')
      },
    })
  }

  const submitRule = () => {
    const name = ruleName.trim()
    if (!name) {
      message.warning('请输入规则名称')
      return
    }
    const resolvedDesc = ruleDesc.trim() || dimLabel(ruleOrder, ruleLayout, rulePairing)
    const resetForm = () => {
      setRuleName('')
      setRuleDesc('')
      setRuleOrder('roster')
      setRuleLayout('normal')
      setRulePairing('none')
      setEditTemplateId(undefined)
      setRuleModalOpen(false)
    }
    if (editTemplateId) {
      setTemplates((prev) =>
        prev.map((t) =>
          t.id === editTemplateId
            ? { ...t, label: name, desc: resolvedDesc, order: ruleOrder, layout: ruleLayout, pairing: rulePairing }
            : t,
        ),
      )
      resetForm()
      message.success('规则模板已更新')
      return
    }
    const id = `custom-${Date.now()}`
    setTemplates((prev) => [
      ...prev,
      {
        id,
        label: name,
        desc: resolvedDesc,
        icon: 'clipboard',
        color: '#64748b',
        order: ruleOrder,
        layout: ruleLayout,
        pairing: rulePairing,
      },
    ])
    setSelectedTemplateId(id)
    resetForm()
    message.success('规则模板已创建')
  }

  const startEdit = (record: RuleTemplate) => {
    setRuleName(record.label)
    setRuleDesc(record.desc === dimLabel(record.order, record.layout, record.pairing) ? '' : record.desc)
    setRuleOrder(record.order)
    setRuleLayout(record.layout)
    setRulePairing(record.pairing)
    setEditTemplateId(record.id)
    setRuleModalOpen(true)
  }

  const setAsDefault = (id: string) => {
    setDefaultTemplateId(id)
    setSelectedTemplateId(id)
    localStorage.setItem(DEFAULT_KEY, id)
    message.success('已设为默认规则')
  }

  const removeTemplate = (id: string) => {
    modal.confirm({
      title: '删除规则模板',
      content: '确定删除该模板吗？删除后无法恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk() {
        const remaining = templates.filter((t) => t.id !== id)
        setTemplates(remaining)
        if (defaultTemplateId === id) {
          setDefaultTemplateId(remaining[0]?.id ?? '')
          localStorage.setItem(DEFAULT_KEY, remaining[0]?.id ?? '')
        }
        if (selectedTemplateId === id) {
          setSelectedTemplateId(remaining[0]?.id ?? '')
        }
        message.success('规则模板已删除')
      },
    })
  }

  return (
    <Spin spinning={loading}>
      <div className="st-page">
        <PageHeader
          title="班级排座"
          extra={
            activeTab === 'rules' ? (
              <Button
                type="primary"
                icon={<Icon name="plus" size={14} />}
                onClick={() => setRuleModalOpen(true)}
              >
                新建规则
              </Button>
            ) : undefined
          }
        />
        <p className="zh-page-desc">按班级名册生成座位方案，确认后启用并保留历史版本。</p>

        <Tabs
          className="st-tabs"
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as 'rules' | 'seats')}
          items={[
            {
              key: 'rules',
              label: '建立规则',
              children: (
                <div className="st-rules">
                  <TableCard>
                    <Table<RuleTemplate>
                      rowKey="id"
                      size="middle"
                      loading={loading}
                      columns={[
                        {
                          title: '模板名称',
                          dataIndex: 'label',
                          width: 210,
                          render: (label: string, record) => (
                            <span className="st-rule-name">
                              <i style={{ color: record.color, background: `${record.color}1a` }}>
                                <Icon name={record.icon} size={16} />
                              </i>
                              <span className="st-rule-name-text">
                                {label}
                                {defaultTemplateId === record.id && (
                                  <Tag className="st-rule-default">默认</Tag>
                                )}
                              </span>
                            </span>
                          ),
                        },
                        {
                          title: '排序方式',
                          key: 'order',
                          width: 130,
                          render: (_, record) => (
                            <Tag color="blue">{ORDER_LABEL[record.order] || record.order}</Tag>
                          ),
                        },
                        {
                          title: '排布方式',
                          key: 'layout',
                          width: 130,
                          render: (_, record) => (
                            <Tag color="purple">{LAYOUT_LABEL[record.layout] || record.layout}</Tag>
                          ),
                        },
                        {
                          title: '搭配方式',
                          key: 'pairing',
                          width: 130,
                          render: (_, record) =>
                            record.pairing && record.pairing !== 'none' ? (
                              <Tag color="green">{PAIRING_LABEL[record.pairing] || record.pairing}</Tag>
                            ) : (
                              <span className="st-dim-none">—</span>
                            ),
                        },
                        {
                          title: '说明',
                          dataIndex: 'desc',
                          ellipsis: true,
                          render: (desc: string, record) =>
                            desc || dimLabel(record.order, record.layout),
                        },
                        {
                          title: '操作',
                          key: 'action',
                          width: 110,
                          align: 'right',
                          render: (_, record) => (
                            <div className="st-rule-actions">
                              <Button
                                type="text"
                                size="small"
                                title={defaultTemplateId === record.id ? '默认规则' : '设为默认'}
                                icon={<Icon name="star" size={14} />}
                                onClick={() => setAsDefault(record.id)}
                              />
                              <Button
                                type="text"
                                size="small"
                                title="编辑"
                                icon={<Icon name="edit" size={14} />}
                                onClick={() => startEdit(record)}
                              />
                              <Button
                                type="text"
                                size="small"
                                danger
                                title="删除"
                                icon={<Icon name="trash" size={14} />}
                                onClick={() => removeTemplate(record.id)}
                              />
                            </div>
                          ),
                        },
                      ]}
                      dataSource={templates}
                      pagination={{
                        pageSize: RULE_PAGE_SIZE,
                        showSizeChanger: false,
                        showTotal: (total) => `共 ${total} 个模板`,
                      }}
                      locale={{
                        emptyText: (
                          <EmptyState
                            height={200}
                            title="暂无规则模板"
                            desc="点击右上角“新建规则”创建组合模板"
                          />
                        ),
                      }}
                    />
                  </TableCard>
                </div>
              ),
            },
            {
              key: 'seats',
              label: '排座位',
              children: (
                <section className="st-use">
                  <aside className="st-config">
                    <div className="st-panel-title">
                      <h3>使用规则排座</h3>
                      {selectedRule && (
                        <span className="st-current-dims">
                          <Tag>{selectedRule.label}</Tag>
                          <Tag color="blue">{ORDER_LABEL[selectedRule.order]}</Tag>
                          <Tag color="purple">{LAYOUT_LABEL[selectedRule.layout]}</Tag>
                          {selectedRule.pairing !== 'none' && (
                            <Tag color="green">{PAIRING_LABEL[selectedRule.pairing]}</Tag>
                          )}
                        </span>
                      )}
                    </div>

                    <div className="st-rule-select">
                      <label className="st-label">
                        规则模板
                        <Select
                          value={selectedTemplateId}
                          onChange={setSelectedTemplateId}
                          options={templates.map((t) => ({
                            value: t.id,
                            label: t.label,
                          }))}
                        />
                      </label>
                    </div>

                    <label className="st-label">
                      班级
                      <Select
                        value={selectedClassId}
                        onChange={setSelectedClassId}
                        placeholder="选择班级"
                        options={classes.map((item) => ({ label: item.name, value: item.id }))}
                      />
                    </label>

                    <div className="st-size-row">
                      <label className="st-label">
                        行数
                        <InputNumber value={rows} onChange={(v) => setRows(v ?? 1)} min={1} max={20} />
                      </label>
                      <label className="st-label">
                        列数
                        <InputNumber value={cols} onChange={(v) => setCols(v ?? 1)} min={1} max={20} />
                      </label>
                    </div>

                    <div className="st-capacity">
                      <span>教室容量</span>
                      <strong>{capacity}</strong>
                      <small>个座位</small>
                    </div>

                    <label className="st-label">
                      自定义前排学生
                      <Select
                        mode="multiple"
                        value={frontIds}
                        onChange={setFrontIds}
                        placeholder="最多选择 20 人"
                        maxTagCount={2}
                        options={students.map((s) => ({
                          label: s.name,
                          value: s.id,
                          disabled: frontIds.length >= 20 && !frontIds.includes(s.id),
                        }))}
                      />
                    </label>

                    <div className="st-pair-block">
                      <span className="st-label-head">隔离学生（勿相邻）</span>
                      <StudentPairField
                        students={students}
                        pairs={separationPairs}
                        onChange={setSeparationPairs}
                        aPlaceholder="选择甲"
                        bPlaceholder="选择乙"
                      />
                    </div>

                    <div className="st-pair-block">
                      <span className="st-label-head">相邻偏好（想挨着坐）</span>
                      <StudentPairField
                        students={students}
                        pairs={adjacencyPairs}
                        onChange={setAdjacencyPairs}
                        aPlaceholder="选择甲"
                        bPlaceholder="选择乙"
                      />
                    </div>
                  </aside>

                  <section className="st-surface">
                    <div className="st-surface-head">
                    <div>
                      <h3>{className}座位表</h3>
                      <span>
                        {current
                          ? `${ruleLabel} · ${current.seats.length} 名学生`
                          : '尚未生成座位方案'}
                      </span>
                    </div>
                    <div className="st-surface-actions">
                      {current && (
                        <Tag color={current.status === 'active' ? 'success' : 'default'}>
                          {STATUS_LABEL[current.status] || current.status}
                        </Tag>
                      )}
                      <Select
                        value={selectedArrangementId}
                        onChange={(v) => setSelectedArrangementId(v)}
                        placeholder="历史版本"
                        style={{ width: 200 }}
                        options={arrangements.map((item) => ({
                          value: item.id,
                          label: `${item.rows} 行 × ${item.cols} 列 · ${STATUS_LABEL[item.status] || item.status}`,
                        }))}
                      />
                      <Button
                        disabled={!current || current.status === 'active'}
                        onClick={activate}
                      >
                        启用当前方案
                      </Button>
                      <Button
                        type="primary"
                        icon={<Icon name="grid" size={15} />}
                        onClick={generate}
                      >
                        生成座位表
                      </Button>
                    </div>
                  </div>

                  <div className="st-podium">
                    <span>讲台</span>
                  </div>

                  {current ? (
                    <>
                      <div className="st-drag-bar">
                        <span className="st-drag-hint">
                          <Icon name="move" size={14} /> 拖动任意座位卡片可与另一座位交换，或移到空位
                        </span>
                        {dirty && (
                          <div className="st-drag-actions">
                            <Button onClick={() => { setWorkingSeats(current?.seats ?? []); setDirty(false) }}>
                              撤销
                            </Button>
                            <Button type="primary" onClick={saveSeats} loading={loading}>
                              保存调整
                            </Button>
                          </div>
                        )}
                      </div>
                      <DndContext
                        sensors={sensors}
                        collisionDetection={closestCorners}
                        onDragStart={({ active }) => setActiveId(String(active.id))}
                        onDragCancel={() => setActiveId(undefined)}
                        onDragEnd={onDragEnd}
                      >
                        <div
                          className="st-seat-grid"
                          style={{
                            gridTemplateColumns: `repeat(${current.cols}, minmax(92px, 1fr))`,
                          }}
                        >
                          {Array.from({ length: current.rows }, (_, row) => row + 1).map((row) =>
                            Array.from({ length: current.cols }, (_, col) => col + 1).map((col) => (
                              <SeatCell
                                key={`${row}-${col}`}
                                row={row}
                                col={col}
                                seat={seatAt(row, col)}
                                activeId={activeId}
                              />
                            )),
                          )}
                        </div>
                      </DndContext>
                    </>
                  ) : (
                    <div className="st-empty">
                      <Icon name="grid" size={30} />
                      <strong>还没有座位表</strong>
                      <span>切换到“建立规则”设置条件后生成。</span>
                    </div>
                  )}

                  <div className="st-door">前门</div>
                </section>
                </section>
              ),
            },
          ]}
        />

        <Modal
          title={editTemplateId ? '编辑规则模板' : '新建规则模板'}
          open={ruleModalOpen}
          onOk={submitRule}
          onCancel={() => {
            setRuleModalOpen(false)
            setEditTemplateId(undefined)
          }}
          okText={editTemplateId ? '保存' : '创建'}
          cancelText="取消"
          width={460}
        >
          <div className="st-modal-form">
            <label className="st-label">
              规则名称
              <Input
                placeholder="例如：男生后排、优等生居中"
                value={ruleName}
                onChange={(e) => setRuleName(e.target.value)}
                maxLength={20}
              />
            </label>
            <label className="st-label">
              规则说明
              <Input.TextArea
                placeholder="简要描述该规则的适用场景（选填）"
                value={ruleDesc}
                onChange={(e) => setRuleDesc(e.target.value)}
                rows={3}
                maxLength={100}
              />
            </label>
            <label className="st-label">
              排序方式
              <Select
                value={ruleOrder}
                onChange={setRuleOrder}
                options={ORDER_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
              />
            </label>
            <label className="st-label">
              排布方式
              <Select
                value={ruleLayout}
                onChange={setRuleLayout}
                options={LAYOUT_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
              />
            </label>
            <label className="st-label">
              搭配方式
              <Select
                value={rulePairing}
                onChange={setRulePairing}
                options={PAIRING_OPTIONS.map((o) => ({
                  value: o.value,
                  label: o.label,
                }))}
              />
            </label>
            <div className="st-modal-summary">
              组合效果：<b>{dimLabel(ruleOrder, ruleLayout, rulePairing)}</b>
            </div>
          </div>
        </Modal>
      </div>
    </Spin>
  )
}
