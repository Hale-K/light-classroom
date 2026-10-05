import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Key } from 'react'
import {
  App,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Select,
  Space,
  Table,
  Tag,
  Tree,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { DataNode } from 'antd/es/tree'
import { authApi, facilityApi, orgApi, organizationApi, schedulingApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import type { Building, Campus, ClassInfo, FacilityOverview, Grade, OrganizationUnit, ResourceAllocationRule, RoomResource, SchedulingGridConfig } from '@/types'
import AllocationRuleDrawer from './allocation-rule-drawer'
import { hasRoomFeature } from './room-features'

type CampusForm = { name: string; address?: string; student_capacity?: number }
type BuildingForm = { campus_id: number; name: string; code?: string; floor_count: number }
type RoomForm = Omit<RoomResource, 'id' | 'building_name' | 'status' | 'features'> & { multimedia?: boolean }
type BatchRoomForm = { building_id: number; floor: number; count: number; start_number: number; name_prefix: string; capacity: number; multimedia: boolean; is_schedulable: boolean }
type ClassPlanForm = { class_id?: number; class_type: string }
type CreateClassForm = { grade_id: number; name: string; class_type: string }
// (BatchClassForm 不再使用)
type BuildingStatus = 'active' | 'maintenance' | 'disabled'
interface FacilityTreeNode {
  key: string
  node_type: 'campus' | 'building' | 'floor' | 'room'
  name: string
  note?: string | null
  campus?: Campus
  building?: Building
  floorNumber?: number
  room?: RoomResource
  children?: FacilityTreeNode[]
}

const BUILDING_STATUS = [
  { label: '正常使用', value: 'active' },
  { label: '维修中', value: 'maintenance' },
  { label: '已停用', value: 'disabled' },
]
const ROOM_TYPE: Record<RoomResource['room_type'], string> = { classroom: '普通教室', laboratory: '实验室', computer: '计算机房', meeting: '会议室', auditorium: '报告厅', office: '办公室' }
const CLASS_TYPE_OPTIONS = [
  { label: '尖子班', value: 'elite' },
  { label: '重点班', value: 'key' },
  { label: '普通班', value: 'regular' },
  { label: '实验班', value: 'experimental' },
]

function navigationNodes(nodes: FacilityTreeNode[]): DataNode[] {
  return nodes.map((node) => ({
    key: node.key,
    title: <span className="zh-org-tree-title"><span>{node.name}</span><small>{node.children?.length || 0}</small></span>,
    children: node.children ? navigationNodes(node.children) : undefined,
  }))
}
function findNode(nodes: FacilityTreeNode[], key: string): FacilityTreeNode | undefined {
  for (const node of nodes) {
    if (node.key === key) return node
    const child = node.children && findNode(node.children, key)
    if (child) return child
  }
}

function flattenGradeGroups(nodes: OrganizationUnit[]): OrganizationUnit[] {
  return nodes.flatMap((node) => [node, ...flattenGradeGroups(node.children || [])])
    .filter((node) => node.unit_type === 'grade_group' && node.status === 'active' && !!node.cohort_label)
}

function gradeLevelFromName(name: string): number | undefined {
  if (name.includes('高一')) return 1
  if (name.includes('高二')) return 2
  if (name.includes('高三')) return 3
  return undefined
}

/** 卡片式单选组（自定义：排序策略/自定义排序） */
function RadioGroupLike({ value, onChange, options, mini = false }: {
  value: string
  onChange: (v: string) => void
  options: Array<{ label: string; value: string; hint?: string }>
  mini?: boolean
}) {
  return (
    <div className={`cpr-radio-like ${mini ? 'cpr-radio-like-mini' : ''}`} style={{ display: 'flex', gap: mini ? 8 : 12, flexWrap: 'wrap' }}>
      {options.map((opt) => {
        const active = value === opt.value
        return (
          <div
            key={opt.value}
            className={`cpr-radio-like-item ${active ? 'is-active' : ''}`}
            onClick={() => onChange(opt.value)}
            style={{
              padding: mini ? '8px 14px' : '12px 16px',
              flex: mini ? undefined : '1 1 0',
              minWidth: mini ? 120 : 200,
              border: `1px solid ${active ? 'var(--primary-1)' : 'var(--border-2)'}`,
              borderRadius: 12,
              background: active ? 'linear-gradient(135deg, rgba(99,102,241,0.10), rgba(34,197,94,0.05))' : 'var(--bg-2)',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              boxShadow: active ? '0 4px 14px rgba(99,102,241,0.16)' : 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                style={{
                  width: 14, height: 14, borderRadius: '50%',
                  border: `2px solid ${active ? 'var(--primary-1)' : 'var(--border-3)'}`,
                  background: active ? 'var(--primary-1)' : 'transparent',
                  boxShadow: active ? 'inset 0 0 0 3px #fff' : 'none',
                }}
              />
              <b style={{ color: active ? 'var(--text-1)' : 'var(--text-2)' }}>{opt.label}</b>
            </div>
            {opt.hint && (
              <p style={{ margin: '6px 0 0 22px', color: 'var(--text-3)', fontSize: 12, lineHeight: 1.5, paddingRight: 4 }}>
                {opt.hint}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function CampusBuildingsView({ embedded = false, focus = 'resources' }: { embedded?: boolean; focus?: 'resources' | 'allocation' | 'class-planning' }) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [data, setData] = useState<FacilityOverview>()
  const [rooms, setRooms] = useState<RoomResource[]>([])
  const [classes, setClasses] = useState<ClassInfo[]>([])
  const [grades, setGrades] = useState<Grade[]>([])
  const [gradeGroups, setGradeGroups] = useState<OrganizationUnit[]>([])
  const [allocationRules, setAllocationRules] = useState<ResourceAllocationRule[]>([])
  const [loading, setLoading] = useState(false)
  const [campusOpen, setCampusOpen] = useState(false)
  const [buildingOpen, setBuildingOpen] = useState(false)
  const [roomOpen, setRoomOpen] = useState(false)
  const [batchRoomOpen, setBatchRoomOpen] = useState(false)
  const [ruleOpen, setRuleOpen] = useState(false)
  const [viewAllocationRule, setViewAllocationRule] = useState<ResourceAllocationRule>()
  const [saving, setSaving] = useState(false)
  const [statusSavingId, setStatusSavingId] = useState<number>()
  const [selectedKey, setSelectedKey] = useState('space')
  const [expandedKeys, setExpandedKeys] = useState<Key[]>(['space'])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [resourcePage, setResourcePage] = useState(1)
  const [resourcePageSize, setResourcePageSize] = useState(12)
  const [resourceKeyword, setResourceKeyword] = useState('')
  const [resourceBuildingId, setResourceBuildingId] = useState<number>()
  const [resourceFloor, setResourceFloor] = useState<number>()
  const [resourceTerm, setResourceTerm] = useState<'1' | '2'>('1')
  const [resourceAcademicYear, setResourceAcademicYear] = useState('2026-2027')
  const [gridConfig, setGridConfig] = useState<SchedulingGridConfig | null>(null)
  const [appliedResourceKeyword, setAppliedResourceKeyword] = useState('')
  const [appliedResourceBuildingId, setAppliedResourceBuildingId] = useState<number>()
  const [appliedResourceFloor, setAppliedResourceFloor] = useState<number>()
  const [campusForm] = Form.useForm<CampusForm>()
  const [buildingForm] = Form.useForm<BuildingForm>()
  const [roomForm] = Form.useForm<RoomForm>()
  const [batchRoomForm] = Form.useForm<BatchRoomForm>()
  const [classPlanForm] = Form.useForm<ClassPlanForm>()
  const [createClassForm] = Form.useForm<CreateClassForm>()
  // (batchClassForm 不再使用)
  const [planningRoom, setPlanningRoom] = useState<RoomResource>()
  const [creatingRoomClass, setCreatingRoomClass] = useState<RoomResource>()
  const [batchClassOpen, setBatchClassOpen] = useState(false)
  const [classPlanSaving, setClassPlanSaving] = useState(false)
  // (旧版 batchClassForm / batchClassRooms / batchStudentCount 已移除，改用新版 state 字段)

  // 新版按需生成班级 Modal
  type ClassTypeKey = 'elite' | 'key' | 'experimental' | 'regular'
  type ClassPlanningPreview = Awaited<ReturnType<typeof facilityApi.classPlanningPreview>>
  const [planGradeId, setPlanGradeId] = useState<number | null>(null)
  const [planGradeGroupId, setPlanGradeGroupId] = useState<number | null>(null)
  const [planCohortLabel, setPlanCohortLabel] = useState<string | null>(null)
  const [planTypeCounts, setPlanTypeCounts] = useState<Record<ClassTypeKey, number>>({
    elite: 0, key: 0, experimental: 0, regular: 0,
  })
  const [planStrategy, setPlanStrategy] = useState<'random' | 'snake'>('random')
  const [planBuildingPrefs, setPlanBuildingPrefs] = useState<Record<number, ClassTypeKey[]>>({}) // building_id → allowed types
  const [planPreview, setPlanPreview] = useState<ClassPlanningPreview | null>(null)
  const [planPreviewLoading, setPlanPreviewLoading] = useState(false)
  const [planSkipGenerated, setPlanSkipGenerated] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [overview, roomItems, classItems, gradeItems, ruleItems, orgTree] = await Promise.all([
        facilityApi.overview(), facilityApi.rooms({ academic_year: resourceAcademicYear, term: resourceTerm }), orgApi.classes(), orgApi.grades(), facilityApi.allocationRules({ academic_year: resourceAcademicYear, term: resourceTerm }), organizationApi.tree(),
      ])
      setData(overview); setRooms(roomItems); setClasses(classItems); setGrades(gradeItems); setAllocationRules(ruleItems)
      setGradeGroups(flattenGradeGroups(orgTree.units))
      const configuredGrid = await schedulingApi.gridConfig({ academic_year: resourceAcademicYear, term: resourceTerm }).catch(() => null)
      setGridConfig(configuredGrid)
    }
    catch (error) { message.error(error instanceof Error ? error.message : '加载校区楼宇失败') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    void authApi.academicYears().then((settings) => {
      if (settings.current_term) setResourceTerm(settings.current_term)
      if (settings.current_academic_year) setResourceAcademicYear(settings.current_academic_year)
    }).catch(() => undefined)
  }, [])
  useEffect(() => { void load() }, [resourceAcademicYear, resourceTerm])

  const createCampus = async (values: CampusForm) => {
    setSaving(true)
    try {
      await facilityApi.createCampus({ name: values.name.trim(), address: values.address?.trim() || undefined, student_capacity: values.student_capacity })
      setCampusOpen(false); campusForm.resetFields(); message.success('校区已创建'); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '创建校区失败') }
    finally { setSaving(false) }
  }

  const createBuilding = async (values: BuildingForm) => {
    setSaving(true)
    try {
      await facilityApi.createBuilding({ ...values, name: values.name.trim(), code: values.code?.trim() || undefined })
      setBuildingOpen(false); buildingForm.resetFields(); message.success('楼宇已创建'); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '创建楼宇失败') }
    finally { setSaving(false) }
  }

  const createRoom = async (values: RoomForm) => {
    setSaving(true)
    try {
      await facilityApi.createRoom({ ...values, name: values.name.trim(), code: values.code?.trim() || undefined, features: values.multimedia ? ['multimedia'] : [] })
      setRoomOpen(false); roomForm.resetFields(); message.success('场室已创建'); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '场室创建失败') }
    finally { setSaving(false) }
  }

  const createRoomsBatch = async (values: BatchRoomForm) => {
    setSaving(true)
    try {
      const result = await facilityApi.createRoomsBatch(values)
      setBatchRoomOpen(false)
      batchRoomForm.resetFields()
      const skippedText = result.skipped_count ? `，跳过已存在 ${result.skipped_count} 间` : ''
      message.success(`已生成 ${result.created_count} 间普通教室${skippedText}`)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '批量生成教室失败') }
    finally { setSaving(false) }
  }

  const treeData = useMemo<FacilityTreeNode[]>(() => (data?.campuses || []).map((campus) => {
    const children = (data?.buildings || []).filter((building) => building.campus_id === campus.id).map((building) => {
      const buildingRooms = rooms.filter((room) => room.building_id === building.id)
      const floors = [...new Set(buildingRooms.map((room) => room.floor))].sort((a, b) => a - b)
      const floorChildren = floors.map((floor) => {
        const floorRooms = buildingRooms.filter((room) => room.floor === floor)
        return {
          key: `floor-${building.id}-${floor}`,
          node_type: 'floor' as const,
          name: `${floor}层`,
          note: `${floorRooms.length} 间场室`,
          floorNumber: floor,
          building,
          children: floorRooms.map((room) => ({ key: `room-${room.id}`, node_type: 'room' as const, name: room.name, note: room.code, room })),
        }
      })
      return { key: `building-${building.id}`, node_type: 'building' as const, name: building.name, note: building.code, building, children: floorChildren.length ? floorChildren : undefined }
    })
    return {
      key: `campus-${campus.id}`,
      node_type: 'campus' as const,
      name: campus.name,
      note: campus.address,
      campus,
      children: children.length ? children : undefined,
    }
  }), [data, rooms])
  useEffect(() => { setExpandedKeys(['space', ...treeData.map((campus) => campus.key)]) }, [treeData])
  const selectedNode = selectedKey === 'space' ? undefined : findNode(treeData, selectedKey)
  const visibleNodes = selectedKey === 'space' ? treeData : selectedNode?.node_type === 'room' ? [selectedNode] : selectedNode?.children || []
  const pagedVisibleNodes = useMemo(
    () => visibleNodes.slice((page - 1) * pageSize, page * pageSize),
    [visibleNodes, page, pageSize],
  )
  const selectedLabel = selectedKey === 'space' ? '全部空间资源' : selectedNode?.name || '空间资源'
  const navTree: DataNode[] = [{ key: 'space', title: <span className="zh-org-tree-title zh-org-school-title"><span>学校空间</span><small>{data?.stats.room_count || 0}</small></span>, children: navigationNodes(treeData) }]
  const assignedRooms = useMemo(() => rooms.filter((room) => (room.cohort_allocations || []).length > 0), [rooms])
  const resourceFloors = useMemo(() => Array.from(new Set(assignedRooms.map((room) => room.floor))).sort((a, b) => a - b), [assignedRooms])
  const filteredResourceRooms = useMemo(() => {
    const keyword = appliedResourceKeyword.trim().toLowerCase()
    return assignedRooms.filter((room) => {
      const matchesKeyword = !keyword || `${room.name} ${room.code || ''} ${room.building_name}`.toLowerCase().includes(keyword)
      const matchesBuilding = appliedResourceBuildingId === undefined || room.building_id === appliedResourceBuildingId
      const matchesFloor = appliedResourceFloor === undefined || room.floor === appliedResourceFloor
      return matchesKeyword && matchesBuilding && matchesFloor
    })
  }, [assignedRooms, appliedResourceBuildingId, appliedResourceFloor, appliedResourceKeyword])
  const pagedResourceRooms = useMemo(() => filteredResourceRooms.slice((resourcePage - 1) * resourcePageSize, resourcePage * resourcePageSize), [filteredResourceRooms, resourcePage, resourcePageSize])
  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredResourceRooms.length / resourcePageSize))
    if (resourcePage > maxPage) setResourcePage(maxPage)
  }, [filteredResourceRooms.length, resourcePage, resourcePageSize])
  const handleResourceSearch = () => {
    setAppliedResourceKeyword(resourceKeyword)
    setAppliedResourceBuildingId(resourceBuildingId)
    setAppliedResourceFloor(resourceFloor)
    setResourcePage(1)
  }
  const resetResourceFilters = () => { setResourceKeyword(''); setResourceBuildingId(undefined); setResourceFloor(undefined); setAppliedResourceKeyword(''); setAppliedResourceBuildingId(undefined); setAppliedResourceFloor(undefined); setResourcePage(1) }

  const updateStatus = async (building: Building, status: BuildingStatus) => {
    setStatusSavingId(building.id)
    try { await facilityApi.updateBuildingStatus(building.id, status); message.success('楼宇使用状态已更新'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '楼宇状态更新失败') }
    finally { setStatusSavingId(undefined) }
  }

  const openClassPlan = (room: RoomResource) => {
    const currentClass = room.class_assignments?.[0]
    classPlanForm.setFieldsValue({ class_id: currentClass?.id, class_type: classes.find((item) => item.id === currentClass?.id)?.class_type || 'regular' })
    setPlanningRoom(room)
  }

  const openCreateClass = (room: RoomResource) => {
    createClassForm.setFieldsValue({ grade_id: grades[0]?.id, name: '', class_type: 'regular' })
    setCreatingRoomClass(room)
  }

  /** 该年级已经生成过的行政班数量 */
  const planExistingClassCount = useMemo(() => {
    if (!planGradeId) return 0
    return classes.filter((c) => c.grade_id === planGradeId).length
  }, [planGradeId, classes])
  // 可用教室池：与后端 _collect_planning_rooms 对齐 — 必须从已分配届别的教室(assignedRooms)出发，
  // 按年级 campus_id 限定楼宇；再按届别标签匹配；未分配届别的教室(76-38=38间)直接排除在外。
  const planCandidateRooms = useMemo(() => {
    if (!planGradeId) return []
    const grade = grades.find((g) => g.id === planGradeId)
    const campusBuildings = new Set(
      (data?.buildings || []).filter((b) => !grade?.campus_id || b.campus_id === grade.campus_id).map((b) => b.id),
    )
    // 1) 必须从 assignedRooms(已通过资源分配规则分配届别的教室) 出发 + 楼宇匹配 + 普通教室类型
    //    assignedRooms = rooms.filter(r => (r.cohort_allocations || []).length > 0)，因此天然排除了未分配届别的教室
    let base = assignedRooms.filter((r) => r.room_type === 'classroom' && campusBuildings.has(r.building_id))
    // 2) 届别标签匹配：仅保留与该年级届别一致的教室(planGradeCohortLabels来自楼宇内教室的cohort_allocations)
    if (planCohortLabel) {
      base = base.filter((r) => (r.cohort_allocations || []).some((a) => a.cohort_label === planCohortLabel))
    }
    // 3) 跳过已生成过班级占用的教室
    if (planSkipGenerated) {
      base = base.filter((r) => !(r.class_assignments?.length))
    }
    return base.sort((a, b) => a.building_name.localeCompare(b.building_name, 'zh-Hans-CN') || a.floor - b.floor || (a.code || '').localeCompare(b.code || ''))
  }, [planGradeId, data?.buildings, grades, assignedRooms, planCohortLabel, planSkipGenerated])
  /** 剩余可设置：候选教室池减去本次已请求数量，用于 UI 提示 */
  const planTotalRequested = planTypeCounts.elite + planTypeCounts.key + planTypeCounts.experimental + planTypeCounts.regular
  const planRemainingCapacity = Math.max(0, planCandidateRooms.length - planTotalRequested)
  const planIsShortage = planTotalRequested > planCandidateRooms.length && planCandidateRooms.length > 0

  const planBuildingsForBinding = useMemo(() => {
    const ids = new Set(planCandidateRooms.map(r => r.building_id))
    return (data?.buildings || []).filter(b => ids.has(b.id))
  }, [planCandidateRooms, data?.buildings])

  const planBuildingRoomCounts = useMemo(() => {
    const m: Record<number, number> = {}
    for (const r of planCandidateRooms) m[r.building_id] = (m[r.building_id] || 0) + 1
    return m
  }, [planCandidateRooms])

  const runPlanPreview = async () => {
    if (!planGradeId || !planGradeGroupId) { message.error('请先选择所属年级部'); return }
    setPlanPreviewLoading(true)
    setPlanPreview(null)
    try {
      const building_preferences = Object.entries(planBuildingPrefs)
        .filter(([, ts]) => ts.length > 0)
        .map(([bid, preferred_types]) => ({ building_id: Number(bid), preferred_types }))
      const result = await facilityApi.classPlanningPreview({
        grade_id: planGradeId,
        grade_group_id: planGradeGroupId ?? undefined,
        academic_year: resourceAcademicYear,
        term: resourceTerm,
        elite_count: planTypeCounts.elite,
        key_count: planTypeCounts.key,
        experimental_count: planTypeCounts.experimental,
        regular_count: planTypeCounts.regular,
        strategy: planStrategy,
        building_preferences,
        skip_generated: planSkipGenerated,
        inspect_only: planTotalRequested <= 0,
      })
      setPlanPreview(result as any)
      if (planTotalRequested <= 0) {
        message.info(result.available_room_count > 0 ? `当前建议生成 ${result.recommended_class_count} 个班` : '当前年级部没有可生成行政班的教室')
        if (result.recommended_class_count > 0) {
          setPlanTypeCounts({ elite: 0, key: 0, experimental: 0, regular: result.recommended_class_count })
        }
        return
      }
      const remain = result.remaining_pools
      if ((remain.elite + remain.key + remain.experimental + remain.regular) > 0) {
        message.warning(`有部分班级类型未分配满：尖子差 ${remain.elite} / 重点差 ${remain.key} / 实验差 ${remain.experimental} / 普通差 ${remain.regular}`)
      }
    } catch (e: any) {
      message.error(e?.message || '预览失败')
    } finally {
      setPlanPreviewLoading(false)
    }
  }

  const selectPlanningGradeGroup = async (groupId: number | undefined) => {
    const group = gradeGroups.find((item) => item.id === groupId)
    const level = group ? gradeLevelFromName(group.name) : undefined
    const grade = level ? grades.find((item) => item.level === level) : undefined
    setPlanGradeGroupId(groupId ?? null)
    setPlanCohortLabel(group?.cohort_label || null)
    setPlanGradeId(grade?.id ?? null)
    setPlanBuildingPrefs({}); setPlanPreview(null)
    if (!grade || !groupId) {
      setPlanTypeCounts({ elite: 0, key: 0, experimental: 0, regular: 0 })
      return
    }
    try {
      const stats = await facilityApi.classPlanningPreview({
        grade_id: grade.id, grade_group_id: groupId,
        academic_year: resourceAcademicYear,
        term: resourceTerm,
        elite_count: 0, key_count: 0, experimental_count: 0, regular_count: 0,
        strategy: 'snake', skip_generated: true, inspect_only: true,
      })
      setPlanTypeCounts({ elite: 0, key: 0, experimental: 0, regular: stats.recommended_class_count })
    } catch (e: any) {
      setPlanTypeCounts({ elite: 0, key: 0, experimental: 0, regular: 0 })
      message.error(e?.message || '读取年级部资源情况失败')
    }
  }

  const openBatchClassCreation = () => {
    setPlanGradeGroupId(null); setPlanCohortLabel(null); setPlanGradeId(null)
    setPlanTypeCounts({ elite: 0, key: 0, experimental: 0, regular: 0 })
    setPlanStrategy('random')
    setPlanBuildingPrefs({})
    setPlanPreview(null)
    setPlanSkipGenerated(true)
    setBatchClassOpen(true)
  }

  const submitBatchClassCreation = async () => {
    if (!planGradeId) return
    if (!planPreview || !planPreview.items?.length) {
      message.error('请先点击"预览"确认方案'); return
    }
    setClassPlanSaving(true)
    try {
      const building_preferences = Object.entries(planBuildingPrefs)
        .filter(([, ts]) => ts.length > 0)
        .map(([bid, preferred_types]) => ({ building_id: Number(bid), preferred_types }))
      const result = await facilityApi.classPlanningExecute({
        grade_id: planGradeId,
        grade_group_id: planGradeGroupId ?? undefined,
        academic_year: resourceAcademicYear,
        term: resourceTerm,
        elite_count: planTypeCounts.elite,
        key_count: planTypeCounts.key,
        experimental_count: planTypeCounts.experimental,
        regular_count: planTypeCounts.regular,
        strategy: planStrategy,
        building_preferences,
        skip_generated: planSkipGenerated,
        plan: planPreview.items,
      })
      const summary = Object.entries(result.by_type || {}).map(([k, v]) => `${k}${v}`).join('、')
      message.success(`成功生成 ${result.created_count} 个行政班（${summary || '无详情'}）`)
      setBatchClassOpen(false)
      setPlanPreview(null)
      await load()
    } catch (e: any) {
      message.error(e?.message || '生成失败')
    } finally {
      setClassPlanSaving(false)
    }
  }

  const planPreviewColumns = useMemo<ColumnsType<any>>(() => [
    { title: '序号', dataIndex: 'sequence_no', width: 80, render: (v) => <b style={{ color: 'var(--primary-1)' }}>#{v}</b> },
    {
      title: '班级名称', dataIndex: 'proposed_class_name', width: 160,
      render: (v, r) => <div><strong>{v}</strong><Tag style={{ marginLeft: 8 }} color={
        r.class_type === 'elite' ? 'red' :
          r.class_type === 'key' ? 'orange' :
            r.class_type === 'experimental' ? 'purple' : 'blue'
      }>{CLASS_TYPE_OPTIONS.find(o => o.value === r.class_type)?.label}</Tag></div>,
    },
    {
      title: '教室', width: 260, render: (_, r) => <div><strong>{r.building_name}</strong> · {r.floor}层 · {r.room_name}{r.code ? <small style={{ color: 'var(--text-3)', marginLeft: 6 }}>{r.code}</small> : null}</div>,
    },
    { title: '容量', dataIndex: 'capacity', width: 100, render: (v) => `${v} 人` },
  ], [])

  const submitCreateClass = async () => {
    const values = await createClassForm.validateFields().catch(() => null)
    if (!values || !creatingRoomClass) return
    setClassPlanSaving(true)
    try {
      await orgApi.createClass({ ...values, home_room_id: creatingRoomClass.id })
      message.success(`已根据${creatingRoomClass.name}生成行政班`)
      setCreatingRoomClass(undefined)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '行政班生成失败') }
    finally { setClassPlanSaving(false) }
  }

  const submitClassPlan = async () => {
    const values = await classPlanForm.validateFields().catch(() => null)
    if (!values || !planningRoom || !values.class_id) return
    setClassPlanSaving(true)
    try {
      await orgApi.updateClassResourcePlan(values.class_id, { home_room_id: planningRoom.id, class_type: values.class_type })
      message.success(`已将${planningRoom.name}分配给${classes.find((item) => item.id === values.class_id)?.name || '所选班级'}`)
      setPlanningRoom(undefined)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '班级教室分配失败') }
    finally { setClassPlanSaving(false) }
  }

  const columns: ColumnsType<FacilityTreeNode> = [
    { title: '空间节点', dataIndex: 'name', render: (name, row) => <><strong>{name}</strong><div className="facility-cell-note">{row.note || (row.node_type === 'campus' ? '校区' : '未设置楼宇编号')}</div></> },
    { title: '类型', dataIndex: 'node_type', width: 110, render: (_, row) => row.node_type === 'campus' ? '校区' : row.node_type === 'building' ? '楼宇' : row.node_type === 'floor' ? '楼层' : ROOM_TYPE[row.room!.room_type] },
    { title: '规模', width: 120, render: (_, row) => row.campus?.student_capacity ? `${row.campus.student_capacity.toLocaleString()} 人` : row.node_type === 'building' ? `${row.building!.floor_count} 层` : row.node_type === 'floor' ? `${row.children?.length || 0} 间` : row.room ? `${row.room.capacity} 人` : '—' },
    { title: '资源信息', render: (_, row) => row.node_type === 'building' ? `${row.building!.room_count} 间场室 · ${row.building!.multimedia_count} 间多媒体` : row.node_type === 'floor' ? <Space size={[4, 4]} wrap>{[...new Set((row.children || []).flatMap((child) => child.room?.cohort_allocations?.map((item) => item.cohort_label) || []))].map((label) => <Tag key={label}>{label}</Tag>)}</Space> : row.room ? <Space size={[4, 4]} wrap>{hasRoomFeature(row.room.features, 'multimedia') && <Tag>多媒体</Tag>}{row.room.cohort_allocations?.map((item) => <Tag color="blue" key={`${item.rule_id}-${item.cohort_label}`}>{item.cohort_label}·{item.allocation_mode === 'shared' ? '共享' : '专属'}</Tag>)}{row.room.is_schedulable && <Tag>排课</Tag>}{row.room.is_exam_enabled && <Tag>排考</Tag>}</Space> : '—' },
    { title: '使用状态', width: 140, render: (_, row) => row.node_type === 'building' ? <Select size="small" value={row.building!.status} loading={statusSavingId === row.building!.id} options={BUILDING_STATUS} style={{ width: 110 }} onChange={(value) => void updateStatus(row.building!, value as BuildingStatus)} /> : <span className="facility-status"><i />{row.room?.status === 'available' || !row.room ? '正常使用' : row.room.status}</span> },
  ]

  const openBuilding = () => { if (selectedNode?.node_type === 'campus') buildingForm.setFieldValue('campus_id', Number(selectedNode.key.replace('campus-', ''))); setBuildingOpen(true) }
  const openRoom = () => { if (selectedNode?.building) roomForm.setFieldValue('building_id', selectedNode.building.id); setRoomOpen(true) }
  const actions = focus === 'resources'
    ? <div className="facility-actions"><Button onClick={() => setCampusOpen(true)}>新增校区</Button><Button disabled={!data?.campuses.length} onClick={openBuilding}>新增楼宇</Button><Button disabled={!data?.buildings.length} onClick={() => { batchRoomForm.setFieldsValue({ building_id: selectedNode?.building?.id || data?.buildings[0]?.id }); setBatchRoomOpen(true) }}>批量生成教室</Button><Button type="primary" disabled={!data?.buildings.length} onClick={openRoom}>新增场室</Button></div>
    : null
  return <div className={embedded ? 'facility-pane' : 'zh-page facility-page'}>
    {embedded ? <div className="facility-subhead facility-subhead-actions">{actions}</div> : <PageHeader title="空间资源" extra={actions} />}
    {focus === 'resources' && <div className="facility-stats">
      {[['校区', data?.stats.campus_count ?? 0], ['教学楼及楼宇', data?.stats.building_count ?? 0], ['场室总数', data?.stats.room_count ?? 0], ['多媒体场室', data?.stats.multimedia_count ?? 0]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
    </div>}
    {focus === 'resources' && <div className="facility-workspace">
      <aside className="facility-tree-panel" aria-label="空间资源树">
        <div className="zh-organization-panel-title"><Icon name="building" size={16} /><strong>空间资源</strong></div>
        <Tree blockNode treeData={navTree} expandedKeys={expandedKeys} onExpand={setExpandedKeys}
          selectedKeys={[selectedKey]} onSelect={(keys) => { setSelectedKey(String(keys[0] || 'space')); setPage(1) }} />
      </aside>
      <section className="facility-directory" aria-label={`${selectedLabel}内容`}>
        <header className="personnel-directory-head"><div><span>当前节点</span><h3>{selectedLabel}</h3></div><span className="facility-muted">学校空间 → 校区 → 楼宇 → 楼层 → 场室</span></header>
        <Table rowKey="key" columns={columns} dataSource={pagedVisibleNodes} loading={loading} pagination={visibleNodes.length > 10 ? {
          current: page,
          pageSize,
          total: visibleNodes.length,
          onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize) },
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        } : false}
          locale={{ emptyText: <EmptyState icon="building" title="当前节点暂无下级资源" desc="可使用页面右上角按钮继续创建空间资源。" height={240} /> }} />
      </section>
    </div>}
    {(focus === 'allocation' || focus === 'class-planning') && <section className="facility-allocation-resource-list">
      <div className="facility-resource-toolbar">
        {focus === 'allocation' && <header className="facility-resource-list-head"><div><strong>资源分配规则</strong><span>每一行是一条资源分配规则；执行后再到资源详情查看具体教室。</span></div><Button type="primary" onClick={() => { setViewAllocationRule(undefined); setRuleOpen(true) }}>新建分配规则</Button></header>}
        {focus === 'class-planning' && <div className="facility-resource-filters">
        <>
          <Select value={resourceTerm} options={[{ value: '1', label: '上学期资源' }, { value: '2', label: '下学期资源' }]} onChange={setResourceTerm} />
          <Input allowClear value={resourceKeyword} placeholder="搜索教室名称、编号或楼宇" onChange={(event) => setResourceKeyword(event.target.value)} onPressEnter={handleResourceSearch} />
          <Select allowClear value={resourceBuildingId} placeholder="全部教学楼" options={(data?.buildings || []).map((building) => ({ label: building.name, value: building.id }))} onChange={setResourceBuildingId} />
          <Select allowClear value={resourceFloor} placeholder="全部楼层" options={resourceFloors.map((floor) => ({ label: `${floor}层`, value: floor }))} onChange={setResourceFloor} />
          <Button type="primary" onClick={handleResourceSearch}>查询</Button>
          <Button onClick={resetResourceFilters}>重置</Button>
        </>
        {focus === 'class-planning' && <Space className="facility-filters-suffix-actions"><Button type="primary" onClick={openBatchClassCreation}>按需生成班级</Button><Button onClick={() => navigate('/classes')}>进入班级管理</Button></Space>}
        </div>}
      </div>
        {focus === 'allocation' && <>
          <div className="facility-term-toolbar"><span>{resourceAcademicYear} · 当前资源学期</span><Select value={resourceTerm} options={[{ value: '1', label: '上学期' }, { value: '2', label: '下学期' }]} onChange={setResourceTerm} /><span className="facility-muted">{gridConfig ? `课位结构：${gridConfig.days}天 / 每天${gridConfig.periods_per_day}节${gridConfig.enable_evening ? ' · 含晚自习' : ''}` : '课位结构尚未配置'}</span></div>
          <Table rowKey="id" size="middle" dataSource={allocationRules} pagination={{ pageSize: 10, showSizeChanger: false }} columns={[
          { title: '规则名称', dataIndex: 'name', width: 220, render: (value) => <strong>{value}</strong> },
          { title: '目标届别', dataIndex: 'cohort_label', width: 120, render: (value) => <Tag color="blue">{value}</Tag> },
          { title: '适用学年', dataIndex: 'academic_year', width: 130 },
          { title: '学期', dataIndex: 'term', width: 80, render: (value) => value === '1' ? '上学期' : '下学期' },
          { title: '校区', key: 'campus', width: 150, render: (_, row) => data?.campuses.find((campus) => campus.id === row.campus_id)?.name || '—' },
          { title: '资源范围', key: 'scope', render: (_, row) => `${row.building_ids?.length ? `${row.building_ids.length} 栋楼宇` : '全部楼宇'} · ${row.floor_from ?? '不限'}-${row.floor_to ?? '不限'}层${row.room_type ? ` · ${ROOM_TYPE[row.room_type]}` : ''}` },
          { title: '分配方式', dataIndex: 'allocation_mode', width: 100, render: (value) => <Tag>{value === 'shared' ? '共享' : '专属'}</Tag> },
          { title: '匹配教室', dataIndex: 'matched_room_count', width: 100, render: (value) => `${value} 间` },
          { title: '状态', dataIndex: 'status', width: 90, render: (value) => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '生效中' : '已停用'}</Tag> },
          { title: '操作', key: 'action', width: 110, render: (_, row) => <Button type="link" size="small" onClick={() => { setViewAllocationRule(row); setRuleOpen(true) }}>查看资源</Button> },
        ]} locale={{ emptyText: <EmptyState icon="sitemap" title={`暂无${resourceTerm === '1' ? '上' : '下'}学期资源分配规则`} desc="切换学期查看对应资源，或点击右上角“新建分配规则”创建。" height={240} /> }} />
        </>}
      {focus === 'class-planning' && <div className="facility-class-resource-grid">
        {pagedResourceRooms.map((room) => <article className="facility-class-resource-card" key={room.id}>
          <div className="facility-class-resource-card-top"><div><span className="facility-class-resource-kicker">{room.building_name} · {room.floor}层</span><strong>{room.name}</strong></div><Tag color={room.class_assignments?.length ? 'green' : 'gold'}>{room.class_assignments?.length ? '已生成班级' : '待生成班级'}</Tag></div>
          <div className="facility-class-resource-meta"><span>{room.code || '未设置编号'}</span><span>{room.capacity}人容量</span></div>
          <div className="facility-class-resource-cohorts"><span>所属届别</span><Space size={[4, 4]} wrap>{room.cohort_allocations?.map((item) => <Tag color="blue" key={`${item.rule_id}-${item.cohort_label}`}>{item.cohort_label}</Tag>)}</Space></div>
          <div className="facility-class-resource-assignment">{room.class_assignments?.length ? <Space size={[4, 4]} wrap>{room.class_assignments.map((item) => <Tag key={item.id}>{item.name}</Tag>)}</Space> : <span className="pending-text">这间教室还没有生成行政班</span>}</div>
          <Button type={room.class_assignments?.length ? 'default' : 'primary'} block onClick={() => room.class_assignments?.length ? openClassPlan(room) : openCreateClass(room)}>{room.class_assignments?.length ? '调整班级' : '根据此教室生成行政班'}</Button>
        </article>)}
        {!filteredResourceRooms.length && <EmptyState icon="building" title={assignedRooms.length ? '没有匹配的教室' : '暂无可划分教室'} desc={assignedRooms.length ? '请调整查询条件后重试。' : '请先在“资源分配规则”中将教室分配给届别。'} height={240} />}
        {!!filteredResourceRooms.length && <div className="facility-resource-pagination"><span>共 {filteredResourceRooms.length} 间教室</span><Pagination current={resourcePage} pageSize={resourcePageSize} total={filteredResourceRooms.length} showTotal={(total, range) => `${range[0]}-${range[1]} / 共 ${total} 间`} showSizeChanger pageSizeOptions={[12, 24, 36, 48]} onChange={(nextPage, nextPageSize) => { const normalizedPageSize = nextPageSize || resourcePageSize; setResourcePageSize(normalizedPageSize); setResourcePage(normalizedPageSize !== resourcePageSize ? 1 : nextPage) }} /></div>}
      </div>}
    </section>}
    <AllocationRuleDrawer open={ruleOpen} viewRule={viewAllocationRule} currentAcademicYear={resourceAcademicYear} currentTerm={resourceTerm} rooms={rooms} campuses={data?.campuses || []} buildings={data?.buildings || []} onClose={() => { setRuleOpen(false); setViewAllocationRule(undefined) }} onChanged={load} />
    <Modal title="新增校区" open={campusOpen} onCancel={() => setCampusOpen(false)} onOk={() => campusForm.submit()} confirmLoading={saving} okText="创建">
      <Form form={campusForm} layout="vertical" requiredMark={false} onFinish={createCampus}>
        <Form.Item name="name" label="校区名称" rules={[{ required: true, message: '请输入校区名称' }]}><Input placeholder="例如：本部校区" /></Form.Item>
        <Form.Item name="student_capacity" label="规划学生规模"><InputNumber min={1} max={100000} addonAfter="人" style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="address" label="地址"><Input placeholder="校区详细地址（选填）" /></Form.Item>
      </Form>
    </Modal>
    <Modal title="新增楼宇" open={buildingOpen} onCancel={() => setBuildingOpen(false)} onOk={() => buildingForm.submit()} confirmLoading={saving} okText="创建">
      <Form form={buildingForm} layout="vertical" requiredMark={false} onFinish={createBuilding} initialValues={{ floor_count: 5 }}>
        <Form.Item name="campus_id" label="所属校区" rules={[{ required: true, message: '请选择校区' }]}><Select options={data?.campuses.map((item) => ({ label: item.name, value: item.id }))} /></Form.Item>
        <Form.Item name="name" label="楼宇名称" rules={[{ required: true, message: '请输入楼宇名称' }]}><Input placeholder="例如：第一教学楼" /></Form.Item>
        <div className="facility-form-grid"><Form.Item name="code" label="楼宇编号"><Input placeholder="例如：A" /></Form.Item><Form.Item name="floor_count" label="楼层数" rules={[{ required: true }]}><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></div>
      </Form>
    </Modal>
    <Modal title="批量生成普通教室" open={batchRoomOpen} onCancel={() => setBatchRoomOpen(false)} onOk={() => batchRoomForm.submit()} confirmLoading={saving} okText="开始生成" width={600}>
      <div style={{ marginBottom: 16, color: 'var(--text-3)' }}>用于快速准备走班和排课资源。已存在同名教室会自动跳过，不会重复创建。</div>
      <Form form={batchRoomForm} layout="vertical" requiredMark={false} onFinish={createRoomsBatch} initialValues={{ floor: 1, count: 20, start_number: 1, name_prefix: '教室', capacity: 45, multimedia: false, is_schedulable: true }}>
        <Form.Item name="building_id" label="所属楼宇" rules={[{ required: true, message: '请选择楼宇' }]}><Select options={data?.buildings.map((item) => ({ label: `${item.name}${item.code ? `（${item.code}）` : ''}`, value: item.id }))} /></Form.Item>
        <div className="facility-form-grid"><Form.Item name="floor" label="所在楼层" rules={[{ required: true }]}><InputNumber min={-5} max={100} style={{ width: '100%' }} /></Form.Item><Form.Item name="count" label="生成数量" rules={[{ required: true }]}><InputNumber min={1} max={500} style={{ width: '100%' }} /></Form.Item></div>
        <div className="facility-form-grid"><Form.Item name="name_prefix" label="名称前缀" rules={[{ required: true, message: '请输入名称前缀' }]}><Input placeholder="例如：教室" /></Form.Item><Form.Item name="start_number" label="起始编号" rules={[{ required: true }]}><InputNumber min={1} max={9999} style={{ width: '100%' }} /></Form.Item></div>
        <Form.Item name="capacity" label="每间容纳人数" rules={[{ required: true }]}><InputNumber min={1} max={5000} addonAfter="人" style={{ width: '100%' }} /></Form.Item>
        <div className="facility-checks"><Form.Item name="multimedia" valuePropName="checked"><Checkbox>配备多媒体</Checkbox></Form.Item><Form.Item name="is_schedulable" valuePropName="checked"><Checkbox>可用于排课</Checkbox></Form.Item></div>
      </Form>
    </Modal>
    <Modal title="新增场室" open={roomOpen} onCancel={() => setRoomOpen(false)} onOk={() => roomForm.submit()} confirmLoading={saving} okText="创建" width={600}>
      <Form form={roomForm} layout="vertical" requiredMark={false} onFinish={createRoom} initialValues={{ floor: 1, capacity: 40, room_type: 'classroom', is_schedulable: true, is_exam_enabled: false, is_meeting_enabled: false }}>
        <div className="facility-form-grid"><Form.Item name="building_id" label="所属楼宇" rules={[{ required: true, message: '请选择楼宇' }]}><Select options={data?.buildings.map((item) => ({ label: item.name, value: item.id }))} /></Form.Item><Form.Item name="room_type" label="场室类型" rules={[{ required: true }]}><Select options={Object.entries(ROOM_TYPE).map(([value, label]) => ({ value, label }))} /></Form.Item></div>
        <div className="facility-form-grid"><Form.Item name="name" label="场室名称" rules={[{ required: true, message: '请输入场室名称' }]}><Input /></Form.Item><Form.Item name="code" label="场室编号"><Input /></Form.Item></div>
        <div className="facility-form-grid"><Form.Item name="floor" label="所在楼层"><InputNumber min={-5} max={100} style={{ width: '100%' }} /></Form.Item><Form.Item name="capacity" label="容纳人数"><InputNumber min={1} max={5000} style={{ width: '100%' }} /></Form.Item></div>
        <div className="facility-checks"><Form.Item name="multimedia" valuePropName="checked"><Checkbox>配备多媒体</Checkbox></Form.Item><Form.Item name="is_schedulable" valuePropName="checked"><Checkbox>可用于排课</Checkbox></Form.Item><Form.Item name="is_exam_enabled" valuePropName="checked"><Checkbox>可用于排考</Checkbox></Form.Item><Form.Item name="is_meeting_enabled" valuePropName="checked"><Checkbox>可用于会议</Checkbox></Form.Item></div>
      </Form>
    </Modal>
    <Modal title="分配到行政班" open={!!planningRoom} onCancel={() => setPlanningRoom(undefined)} onOk={() => void submitClassPlan()} confirmLoading={classPlanSaving} okText="确认分配" centered destroyOnHidden>
      <div className="facility-plan-room-summary"><strong>{planningRoom?.building_name} · {planningRoom?.floor}层 · {planningRoom?.name}</strong><span>{planningRoom?.capacity}人 · {(planningRoom?.cohort_allocations || []).map((item) => item.cohort_label).join('、') || '未分配届别'}</span></div>
      <Form form={classPlanForm} layout="vertical" requiredMark={false}>
        <Form.Item name="class_id" label="行政班" rules={[{ required: true, message: '请选择要绑定的行政班' }]}><Select showSearch optionFilterProp="label" placeholder="选择行政班" options={classes.map((item) => ({ value: item.id, label: `${item.name} · ${CLASS_TYPE_OPTIONS.find((option) => option.value === item.class_type)?.label || '普通班'}` }))} /></Form.Item>
        <Form.Item name="class_type" label="班级类型" rules={[{ required: true }]}><Select options={CLASS_TYPE_OPTIONS} /></Form.Item>
      </Form>
    </Modal>
    <Modal title="根据教室生成行政班" open={!!creatingRoomClass} onCancel={() => setCreatingRoomClass(undefined)} onOk={() => void submitCreateClass()} confirmLoading={classPlanSaving} okText="生成班级" centered destroyOnHidden>
      <div className="facility-plan-room-summary"><strong>{creatingRoomClass?.building_name} · {creatingRoomClass?.floor}层 · {creatingRoomClass?.name}</strong><span>该教室已完成届别资源分配，确认后才会生成行政班。</span></div>
      <Form form={createClassForm} layout="vertical" requiredMark={false}>
        <Form.Item name="grade_id" label="所属年级" rules={[{ required: true, message: '请选择所属年级' }]}><Select options={grades.map((grade) => ({ value: grade.id, label: grade.name }))} /></Form.Item>
        <Form.Item name="name" label="班级名称" rules={[{ required: true, whitespace: true, message: '请输入班级名称' }]}><Input placeholder="例如：高一（1）班" maxLength={50} /></Form.Item>
        <Form.Item name="class_type" label="班级类型" rules={[{ required: true }]}><Select options={CLASS_TYPE_OPTIONS} /></Form.Item>
      </Form>
    </Modal>
    <Modal
      title={<div className="cpr-modal-title">按需生成行政班<Tag color="blue">预览-修改-生成 三步</Tag></div>}
      open={batchClassOpen}
      onCancel={() => setBatchClassOpen(false)}
      onOk={() => void submitBatchClassCreation()}
      confirmLoading={classPlanSaving}
      okText="确认生成以上方案"
      centered
      destroyOnHidden
      width={1200}
      bodyStyle={{ paddingTop: 12, maxHeight: '82vh', overflowY: 'auto' }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Button onClick={runPlanPreview} type="default" loading={planPreviewLoading} disabled={!planGradeId}>
              预览生成结果
            </Button>
            <Button onClick={() => setPlanPreview(null)} disabled={!planPreview}>清空预览</Button>
            <Tag color="geekblue" style={{ border: 0 }}>
              共生成 <b style={{ color: planTotalRequested ? '#1e293b' : undefined }}>{planTotalRequested || 0}</b> 个班
              {planCandidateRooms.length ? <span style={{ color: 'var(--text-3)' }}> / 可用 {planCandidateRooms.length} 间</span> : null}
            </Tag>
          </Space>
          <Space>
            <Button onClick={() => setBatchClassOpen(false)}>取消</Button>
            <Button
              type="primary"
              disabled={!planPreview?.items?.length || !planGradeId}
              loading={classPlanSaving}
              onClick={() => void submitBatchClassCreation()}
            >
              确认生成以上方案
            </Button>
          </Space>
        </div>
      }
    >
      <div className="cpr-modal">
        {/* Step 1: 年级 + 类型数量 */}
        <Card
          className={`cpr-card cpr-card-grade${planIsShortage ? ' cpr-card-overloaded' : ''}`}
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span>第 1 步 · 指定班级类型规模</span>
              {planGradeId ? (
                <>
                  <Tag color="geekblue" style={{ border: 0, background: '#eff6ff' }}>可用教室池 <b style={{ color: '#1d4ed8' }}>{planCandidateRooms.length}</b> 间</Tag>
                  {planTotalRequested > 0 && (
                    planIsShortage
                      ? <Tag color="red" style={{ border: 0 }}>缺口 <b>{planTotalRequested - planCandidateRooms.length}</b> 间</Tag>
                      : <Tag color="green" style={{ border: 0 }}>富余 <b>{planRemainingCapacity}</b> 间</Tag>
                  )}
                </>
              ) : <Tag>请先选择年级部</Tag>}
            </div>
          }
        >
          {planGradeId && (
            <div className="cpr-stat-triplet">
              <div className={`cpr-stat${planExistingClassCount > 0 ? ' is-muted' : ''}`}>
                <small>本年级已有班级</small>
                <strong style={{ color: planExistingClassCount > 0 ? 'var(--ink)' : '#24885d' }}>{planExistingClassCount}</strong>
                <em>个班</em>
              </div>
              <div className={`cpr-stat${planTotalRequested === 0 ? ' is-muted' : ''}`}>
                <small>本次新增班级</small>
                <strong style={{ color: planTotalRequested === 0 ? 'var(--text-3)' : '#2563eb' }}>{planTotalRequested}</strong>
                <em>个班</em>
              </div>
              <div className={`cpr-stat${planIsShortage ? ' is-shortage' : ''}`}>
                <small>剩余可设置班级</small>
                <strong style={{ color: planIsShortage ? '#b93832' : '#24885d' }}>{planRemainingCapacity}</strong>
                <em>个班</em>
              </div>
              <div className="cpr-stat">
                <small>已分班学生</small>
                <strong>{planPreview?.assigned_student_count ?? 0}</strong>
                <em>人</em>
              </div>
            </div>
          )}
          <div className="cpr-grid-2">
            <Form.Item label="所属年级部" required>
              <Select
                style={{ width: '100%' }}
                value={planGradeGroupId ?? undefined}
                onChange={(v) => void selectPlanningGradeGroup(v)}
                placeholder="先选择年级管理中心中的年级部"
                showSearch
                optionFilterProp="label"
                options={gradeGroups.map((group) => ({ label: group.name, value: group.id }))}
              />
            </Form.Item>
            <Form.Item label="已生成教室处理">
              <Space>
                <Checkbox checked={planSkipGenerated} onChange={(e) => setPlanSkipGenerated(e.target.checked)}>
                  仅使用尚未生成行政班的教室
                </Checkbox>
              </Space>
            </Form.Item>
          </div>
          <div className={`cpr-type-cards${planIsShortage ? ' cpr-type-cards-overload' : ''}`}>
            {CLASS_TYPE_OPTIONS.map((opt, i) => {
              const colors = ['#dc2626', '#ea580c', '#7c3aed', '#0f766e']
              const k = opt.value as ClassTypeKey
              const v = planTypeCounts[k] || 0
              return (
                <div key={opt.value} className={`cpr-type-card cpr-type-${opt.value}`} style={{ borderColor: `${colors[i]}33` }}>
                  <div className="cpr-type-card-top" style={{ background: `${colors[i]}14` }}>
                    <span className="cpr-type-dot" style={{ background: colors[i] }} />
                    <span className="cpr-type-label">{opt.label}</span>
                    <Tag color={colors[i]} style={{ marginLeft: 'auto' }}>{v} 班</Tag>
                  </div>
                  <div className="cpr-type-card-body">
                    <InputNumber
                      min={0}
                      max={Math.max(100, planCandidateRooms.length)}
                      value={v}
                      onChange={(n) => setPlanTypeCounts({ ...planTypeCounts, [k]: Number(n || 0) })}
                      addonBefore="数量"
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>

        {/* Step 2: 策略 + 栋绑定 */}
        <Card className="cpr-card" title="第 2 步 · 教室排序与栋类型绑定">
          <div className="cpr-grid-2">
            <Form.Item label="排序策略" required style={{ marginBottom: 0 }}>
              <RadioGroupLike
                value={planStrategy}
                onChange={(v) => { setPlanStrategy(v as any); setPlanPreview(null) }}
                options={[
                  { label: '随机分配', value: 'random', hint: '打乱候选教室后依次分配类型' },
                  { label: '蛇形排序', value: 'snake', hint: '按楼宇、楼层和编号交替排序，尽量均衡分布' },
                ]}
              />
            </Form.Item>
          </div>

          {/* 栋绑定 */}
<div className="cpr-bindings-title">
  <strong>楼栋·班级类型绑定</strong>
</div>
          <div className="cpr-binding-grid">
            {planBuildingsForBinding.map((b) => {
              const checked = planBuildingPrefs[b.id] ?? []
              const allChecked = checked.length === 4
              const roomCount = planBuildingRoomCounts[b.id] || 0
              return (
                <div key={b.id} className={`cpr-binding-card${roomCount === 0 ? ' cpr-binding-empty' : ''}`}>
                  <div className="cpr-binding-card-head">
                    <b>{b.name}</b>
                    {b.code && <Tag style={{ marginLeft: 4 }}>{b.code}栋</Tag>}
                    <Tag color={roomCount ? 'geekblue' : 'default'} style={{ marginLeft: 8, border: 0 }}>
                      <b style={{ fontSize: 13 }}>{roomCount}</b> 间教室
                    </Tag>
                    <Tag
                      style={{ marginLeft: 'auto' }}
                      color={allChecked ? 'default' : (checked.length ? 'cyan' : 'warning')}
                    >
                      {allChecked ? '允许全部类型' : checked.length ? `仅 ${checked.length} 类` : '未绑定（全限制）'}
                    </Tag>
                  </div>
                  <div className="cpr-binding-card-body">
                    <Checkbox
                      indeterminate={checked.length > 0 && !allChecked}
                      checked={allChecked}
                      onChange={(e) => setPlanBuildingPrefs({
                        ...planBuildingPrefs,
                        [b.id]: e.target.checked ? ['elite', 'key', 'experimental', 'regular'] as ClassTypeKey[] : [],
                      })}
                    >
                      全部
                    </Checkbox>
                    {CLASS_TYPE_OPTIONS.map((opt) => (
                      <Checkbox
                        key={opt.value}
                        checked={checked.includes(opt.value as ClassTypeKey)}
                        onChange={(e) => {
                          const cur = new Set(checked)
                          if (e.target.checked) cur.add(opt.value as ClassTypeKey)
                          else cur.delete(opt.value as ClassTypeKey)
                          setPlanBuildingPrefs({ ...planBuildingPrefs, [b.id]: Array.from(cur) })
                        }}
                      >
                        {opt.label}
                      </Checkbox>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>

        </Card>

        {/* Step 3: 预览结果 */}
        <Card
          className="cpr-card cpr-preview-card"
          title={
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span>第 3 步 · 预览生成结果（教室自动按序编号）</span>
              {planPreview && <Tag color="success">{planPreview.grade_name} · 已生成班级序从 #{(planPreview.existing_count || 0) + 1} 起</Tag>}
            </div>
          }
        >
          {!planPreview && !planPreviewLoading && (
            <div className="cpr-empty-hint" style={{ padding: '40px 0' }}>
              点击左上角「预览生成结果」查看将要生成的班级分配方案。
            </div>
          )}
          {planPreviewLoading && (
            <div className="cpr-empty-hint" style={{ padding: '40px 0' }}>正在生成预览…</div>
          )}
          {planPreview && (
            <>
              <Space className="cpr-preview-summary" wrap style={{ marginBottom: 12 }}>
                <Tag color="purple">候选教室 {planPreview.available_room_count} 间</Tag>
                <Tag color="cyan">请求生成 {planPreview.requested_total} 个班</Tag>
                <Tag color="blue">实际生成 {planPreview.item_count} 条（{(planPreview.remaining_pools.elite + planPreview.remaining_pools.key + planPreview.remaining_pools.experimental + planPreview.remaining_pools.regular) || '0'} 条未满足）</Tag>
                {Object.entries(planPreview.remaining_pools).filter(([, v]: [any, number]) => v > 0).map(([k, v]: [string, number]) => (
                  <Tag key={k} color="red">未满：{CLASS_TYPE_OPTIONS.find((o: any) => o.value === k)?.label} {v}</Tag>
                ))}
              </Space>
              <div className="cpr-preview-grid">
                {planPreview.items.map((r: any) => {
                  const typeColor = r.class_type === 'elite' ? '#dc2626' : r.class_type === 'key' ? '#ea580c' : r.class_type === 'experimental' ? '#7c3aed' : '#0f766e'
                  const typeLabel = CLASS_TYPE_OPTIONS.find(o => o.value === r.class_type)?.label
                  return (
                    <div key={r.room_id} className="cpr-preview-result-card" style={{ borderLeft: `4px solid ${typeColor}` }}>
                      <div className="cpr-preview-result-card-head">
                        <span className="cpr-preview-seq" style={{ background: typeColor }}>#{r.sequence_no}</span>
                        <Tag color={typeColor} style={{ border: 0, marginLeft: 'auto' }}>{typeLabel}</Tag>
                      </div>
                      <div className="cpr-preview-result-card-body">
                        <strong className="cpr-preview-classname">{r.proposed_class_name}</strong>
                        <div className="cpr-preview-room-line">
                          <span className="cpr-preview-building">{r.building_name}</span>
                          <span className="cpr-preview-sep">·</span>
                          <span>{r.floor}层</span>
                          <span className="cpr-preview-sep">·</span>
                          <span>{r.room_name}</span>
                          {r.code ? <span className="cpr-preview-code">{r.code}</span> : null}
                        </div>
                        <div className="cpr-preview-meta">
                          <Tag color="blue" style={{ border: 0 }}>容量 {r.capacity} 人</Tag>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
              <details className="cpr-preview-details" style={{ marginTop: 8 }}>
                <summary>表格视图（便于核对序号）</summary>
                <Table<typeof planPreview.items[number]>
                  rowKey={(r) => r.room_id}
                  size="small"
                  dataSource={planPreview.items}
                  columns={planPreviewColumns}
                  scroll={{ x: 720 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  style={{ marginTop: 10 }}
                />
              </details>
            </>
          )}
        </Card>
      </div>
    </Modal>
  </div>
}
