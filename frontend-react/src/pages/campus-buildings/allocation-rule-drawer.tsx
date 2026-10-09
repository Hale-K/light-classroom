import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space, Tag } from 'antd'
import { authApi, facilityApi, organizationApi } from '@/api'
import type { Building, Campus, OrganizationUnit, ResourceAllocationRule, RoomAllocationPreview, RoomResource } from '@/types'
import { flattenOrganizationUnits } from '@/pages/organization/tree-utils'

type RuleForm = {
  name: string
  target_grade_unit_id: number
  academic_year: string
  term: '1' | '2'
  campus_id: number
  building_ids?: number[]
  floor_from?: number
  floor_to?: number
  room_type?: RoomResource['room_type']
  min_capacity?: number
  required_feature?: string
  allocation_mode: 'exclusive' | 'shared'
}

const ROOM_TYPES = [
  { value: 'classroom', label: '普通教室' },
  { value: 'laboratory', label: '实验室' },
  { value: 'computer', label: '计算机房' },
  { value: 'auditorium', label: '报告厅' },
]

export default function AllocationRuleDrawer({
  open,
  campuses,
  buildings,
  rooms = [],
  viewRule,
  currentAcademicYear,
  currentTerm,
  onClose,
  onChanged,
}: {
  open: boolean
  campuses: Campus[]
  buildings: Building[]
  rooms?: RoomResource[]
  viewRule?: ResourceAllocationRule
  currentAcademicYear: string
  currentTerm: '1' | '2'
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [form] = Form.useForm<RuleForm>()
  const [gradeUnitOptions, setGradeUnitOptions] = useState<Array<{ value: number; label: string }>>([])
  const [gradeUnits, setGradeUnits] = useState<OrganizationUnit[]>([])
  const [academicYearOptions, setAcademicYearOptions] = useState<Array<{ value: string; label: string }>>([])
  const [saving, setSaving] = useState(false)
  const [previewCount, setPreviewCount] = useState<number>()
  const [occupiedCount, setOccupiedCount] = useState(0)
  const [previewRooms, setPreviewRooms] = useState<RoomAllocationPreview[]>([])
  const [selectedRoomIds, setSelectedRoomIds] = useState<number[]>([])
  const [studentCount, setStudentCount] = useState<number | null>(null)
  const [availableCapacity, setAvailableCapacity] = useState(0)
  const [resourceAllocationMode, setResourceAllocationMode] = useState<'cohort_capacity' | 'shared_pool'>('cohort_capacity')
  const viewedRooms = useMemo(
    () => viewRule ? rooms.filter((room) => room.cohort_allocations?.some((item) => item.rule_id === viewRule.id)) : [],
    [rooms, viewRule],
  )
  useEffect(() => {
    if (!open || viewRule) return
    // 规则的适用范围跟随系统当前学年学期，避免在不同页面上下文间误存错期次。
    form.setFieldsValue({ academic_year: currentAcademicYear, term: currentTerm })
    void Promise.all([authApi.academicYears(), organizationApi.tree()]).then(([settings, tree]) => {
      const allGradeUnits = flattenOrganizationUnits(tree.units).filter((item) => item.unit_type === 'grade_group' && item.status === 'active')
      const units = allGradeUnits.filter((item) => item.cohort_label)
      setGradeUnits(allGradeUnits)
      setGradeUnitOptions(units
        .sort((left, right) => (right.cohort_label || '').localeCompare(left.cohort_label || '') || left.name.localeCompare(right.name, 'zh-CN'))
        .map((item) => ({ value: item.id, label: `${item.cohort_label} · ${item.name}` })))
      setAcademicYearOptions(Array.from(new Set(settings.years.flatMap((item) => Object.values(item.grade_years)))).sort().map((value) => ({ value, label: `${value}学年` })))
      if (settings.current_entry_year !== null) {
        const currentGradeUnit = units.find((item) => String(item.cohort_label).replace('届', '') === String(settings.current_entry_year))
        if (currentGradeUnit) form.setFieldValue('target_grade_unit_id', currentGradeUnit.id)
        const current = settings.years.find((item) => item.entry_year === settings.current_entry_year)
        const firstYear = current ? Object.values(current.grade_years)[0] : undefined
        if (firstYear) form.setFieldValue('academic_year', firstYear)
      }
      form.setFieldsValue({ academic_year: currentAcademicYear, term: currentTerm })
    }).catch(() => {
      setGradeUnitOptions([])
    })
  }, [currentAcademicYear, currentTerm, form, open, viewRule])
  const campusId = Form.useWatch('campus_id', form)
  const normalizedValues = async () => {
    const values = await form.validateFields()
    const targetUnit = gradeUnits.find((item) => item.id === values.target_grade_unit_id)
    if (!targetUnit?.cohort_label) throw new Error('所选年级部未配置届编码，请先完善组织架构')
    const { target_grade_unit_id: _targetGradeUnitId, ...rest } = values
    return Object.fromEntries(Object.entries({
      ...rest,
      cohort_label: targetUnit.cohort_label,
      academic_year: values.academic_year,
    }).filter(([, value]) => value !== undefined && value !== ''))
  }
  const preview = async () => {
    try {
      const result = await facilityApi.previewAllocationRule(await normalizedValues())
      setPreviewCount(result.matched_count)
      const rooms = result.rooms || []
      setOccupiedCount(result.occupied_count ?? 0)
      setPreviewRooms(rooms)
      setStudentCount(result.student_count ?? null)
      setAvailableCapacity(result.available_capacity ?? 0)
      setResourceAllocationMode(result.resource_allocation_mode ?? 'cohort_capacity')
      // 预览只展示匹配结果；场室必须由用户明确勾选，避免误把整组教室分配出去。
      setSelectedRoomIds([])
      message.success(result.resource_allocation_mode === 'shared_pool'
        ? `已展示 ${result.rooms.length} 间场室，请手动勾选共享教室`
        : `已展示 ${result.rooms.length} 间场室，请手动勾选要分配的教室`)
    } catch (error) { message.error(error instanceof Error ? error.message : '规则预览失败') }
  }
  const create = async () => {
    if (!previewRooms.length) {
      message.warning('请先点击“预览匹配”，确认场室后再执行划分')
      return
    }
    if (!selectedRoomIds.length) {
      message.warning('请至少勾选一间可分配场室')
      return
    }
    setSaving(true)
    try {
      const result = await facilityApi.createAllocationRule({
        ...(await normalizedValues()),
        room_ids: selectedRoomIds,
      })
      message.success(`已将 ${result.matched_room_count} 间场室划分给 ${result.cohort_label}`)
      form.resetFields(); setPreviewCount(undefined); setOccupiedCount(0); setPreviewRooms([]); setSelectedRoomIds([]); setStudentCount(null); setAvailableCapacity(0); await onChanged(); onClose()
    } catch (error) { message.error(error instanceof Error ? error.message : '资源划分失败') }
    finally { setSaving(false) }
  }
  const toggleRoom = (roomId: number, checked: boolean) => {
    setSelectedRoomIds((current) => checked ? [...current, roomId] : current.filter((id) => id !== roomId))
  }
  const roomTypeLabel: Record<RoomResource['room_type'], string> = {
    classroom: '普通教室', laboratory: '实验室', computer: '计算机房', meeting: '会议室', auditorium: '报告厅', office: '办公室',
  }
  const stateLabel: Record<RoomAllocationPreview['state'], string> = {
    available: '本次可选', occupied: '已被占用', current: '本届已分配', ineligible: '不符合规则', unavailable: '不可用',
  }
  const selectedCapacity = previewRooms.filter((room) => selectedRoomIds.includes(room.id)).reduce((total, room) => total + room.capacity, 0)
  const capacitySufficient = resourceAllocationMode === 'shared_pool'
    ? selectedRoomIds.length > 0
    : studentCount === null || selectedCapacity >= studentCount
  const capacityStatus = resourceAllocationMode === 'shared_pool'
    ? (capacitySufficient ? '共享池可用' : '请至少选择一间教室')
    : studentCount === null ? '无法校验' : capacitySufficient ? '满足要求' : '不满足要求'
  const capacitySuggestion = resourceAllocationMode === 'shared_pool'
    ? '走班制教室按教学班共享池使用，不把全年级学生人数累加为教室总容量；生成教学班时再校验每个教学班的单间容量。'
    : studentCount === null
    ? '建议先为目标届别绑定年级，并确认学生档案已归属该年级。'
    : capacitySufficient
      ? '当前勾选场室容量可以覆盖目标届别学生，可继续执行划分。'
      : `建议扩大楼层范围、选择其他教学楼或增加 ${studentCount - selectedCapacity} 个座位容量。`

  return <Modal
    title={viewRule ? `${viewRule.name} · 已分配资源` : '届别资源划分规则'}
    open={open}
    onCancel={onClose}
    width={760}
    centered
    footer={null}
    destroyOnHidden
    className="facility-rule-modal"
  >
    {viewRule ? <section className="facility-view-allocation">
      <div className="facility-view-allocation-meta">
        <span>目标届别：<strong>{viewRule.cohort_label}</strong></span>
        <span>适用学年：<strong>{viewRule.academic_year}</strong></span>
        <span>适用学期：<strong>{viewRule.term === '1' ? '上学期' : '下学期'}</strong></span>
        <span>匹配教室：<strong>{viewRule.matched_room_count} 间</strong></span>
        <span>资源归属：<strong>{viewRule.allocation_mode === 'shared' ? '同届复用' : '独占'}</strong></span>
      </div>
      <ViewAllocationPreview rooms={viewedRooms} />
    </section> : <>
    <Form
      form={form}
      layout="vertical"
      initialValues={{ term: currentTerm, academic_year: currentAcademicYear, allocation_mode: 'exclusive' }}
      requiredMark
    >
      <div className="facility-form-grid">
        <Form.Item name="name" label="规则名称" rules={[
          { required: true, message: '请输入规则名称' },
          { whitespace: true, message: '规则名称不能只包含空格' },
          { max: 100, message: '规则名称不能超过100个字符' },
        ]}><Input placeholder="例如：2029届低楼层普通教室" maxLength={100} /></Form.Item>
        <Form.Item
          name="target_grade_unit_id"
          label="目标年级部"
          rules={[{ required: true, message: '请选择目标年级部' }]}
          extra={gradeUnitOptions.length === 0 && (
            <span>
              尚未配置年级部，
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => { onClose(); navigate('/staff?tab=organization') }}
              >去设置</Button>
            </span>
          )}
        >
          <Select
            showSearch
            optionFilterProp="label"
            options={gradeUnitOptions}
            placeholder={gradeUnitOptions.length === 0 ? '暂无已配置届别的年级部' : '选择年级部'}
            notFoundContent={
              <div style={{ padding: 8, textAlign: 'center' }}>
                暂无年级部
                <Button
                  type="link"
                  size="small"
                  onClick={() => { onClose(); navigate('/staff?tab=organization') }}
                >去设置</Button>
              </div>
            }
          />
        </Form.Item>
      </div>
      <div className="facility-form-grid">
        <Form.Item name="academic_year" label="适用学年" extra="来自系统设置" rules={[{ required: true, message: '未读取到当前学年' }]}><Select disabled options={academicYearOptions} placeholder="读取当前学年" /></Form.Item>
        <Form.Item name="term" label="适用学期" extra="来自系统设置" rules={[{ required: true, message: '未读取到当前学期' }]}><Select disabled options={[{ value: '1', label: '上学期' }, { value: '2', label: '下学期' }]} placeholder="读取当前学期" /></Form.Item>
      </div>
      <div className="facility-form-grid">
        <Form.Item name="campus_id" label="校区" rules={[{ required: true, message: '请选择校区' }]}><Select options={campuses.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
        <Form.Item name="building_ids" label="楼宇范围"><Select mode="multiple" allowClear placeholder="全部楼宇，可多选" options={buildings.filter((item) => item.campus_id === campusId).map((item) => ({ value: item.id, label: item.name }))} maxTagCount="responsive" /></Form.Item>
      </div>
      <div className="facility-form-grid">
        <Form.Item label="楼层范围"><Space.Compact block><Form.Item name="floor_from" noStyle rules={[({ getFieldValue }) => ({ validator: async (_, value) => { const end = getFieldValue('floor_to'); if (value !== undefined && end !== undefined && value > end) throw new Error('起始楼层不能大于结束楼层') } })]}><InputNumber min={-5} max={100} placeholder="起始" style={{ width: '50%' }} /></Form.Item><Form.Item name="floor_to" noStyle dependencies={['floor_from']} rules={[({ getFieldValue }) => ({ validator: async (_, value) => { const start = getFieldValue('floor_from'); if (start !== undefined && value !== undefined && start > value) throw new Error('结束楼层不能小于起始楼层') } })]}><InputNumber min={-5} max={100} placeholder="结束" style={{ width: '50%' }} /></Form.Item></Space.Compact></Form.Item>
        <Form.Item name="room_type" label="场室类型"><Select allowClear placeholder="全部类型" options={ROOM_TYPES} /></Form.Item>
      </div>
      <div className="facility-form-grid">
        <Form.Item name="min_capacity" label="最低容量" rules={[{ type: 'number', min: 1, max: 5000, message: '最低容量应为1至5000之间的整数' }]}><InputNumber min={1} max={5000} addonAfter="人" style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="required_feature" label="必备能力"><Select allowClear placeholder="不限制" options={[{ value: 'multimedia', label: '多媒体' }]} /></Form.Item>
      </div>
      <Form.Item name="allocation_mode" label="资源归属方式" extra="同届复用只适用于当前学年、当前学期和当前届别；不允许把高一教室跨届分给高二，也不表示同一课位可同时安排多个班级。" rules={[{ required: true, message: '请选择资源归属方式' }]}><Select options={[{ value: 'shared', label: '同届复用：同一届内可用于多个教学班' }, { value: 'exclusive', label: '独占：教室只分配给当前届别' }]} /></Form.Item>
      <Space wrap><Button onClick={() => void preview()}>预览匹配</Button><Button type="primary" loading={saving} disabled={!selectedRoomIds.length || !capacitySufficient} onClick={() => void create()}>执行划分</Button>{previewCount !== undefined && <span className="facility-muted">可选 {selectedRoomIds.length} 间 · 已占用 {occupiedCount} 间</span>}</Space>
    </Form>
    {previewRooms.length > 0 && <div className={`facility-capacity-summary ${capacitySufficient ? 'is-ok' : 'is-shortage'}`} role="status">
      <div className="facility-capacity-result"><strong>{capacityStatus}</strong><span>{capacitySuggestion}</span></div><div className="facility-capacity-metrics">{resourceAllocationMode === 'shared_pool' ? <><span>年级学生总数（参考） {studentCount === null ? '未建立关联' : `${studentCount} 人`}</span><span>共享池最大容量 {Math.max(0, ...previewRooms.filter((room) => room.selectable).map((room) => room.capacity))} 人</span><span>已选共享教室 {selectedRoomIds.length} 间</span></> : <><span>目标届别学生 {studentCount === null ? '未建立关联' : `${studentCount} 人`}</span><span>全部可选容量 {availableCapacity} 人</span><span>当前勾选容量 {selectedCapacity} 人</span></>}</div>
    </div>}
    {previewRooms.length > 0 && <section className="facility-room-preview" aria-label="场室匹配预览">
      <header className="facility-room-preview-head">
        <div><strong>楼宇场室分布</strong><span>勾选绿色场室后执行划分，红色场室表示已被其他届别占用</span></div>
        <div className="facility-room-legend"><span className="is-available">可选</span><span className="is-occupied">已占用</span><span className="is-muted">不可用/不符合</span></div>
      </header>
      <div className="facility-room-grid">
        {previewRooms.map((room) => <label key={room.id} className={`facility-room-option is-${room.state}`}>
          <Checkbox checked={selectedRoomIds.includes(room.id)} disabled={!room.selectable} onChange={(event) => toggleRoom(room.id, event.target.checked)} />
          <span className="facility-room-option-copy"><strong>{room.building_name} · {room.floor}层 · {room.name}</strong><small>{room.code || '未设置编号'} · {room.capacity}人 · {roomTypeLabel[room.room_type]}</small>{room.occupied_by.length > 0 && <small>已分配：{room.occupied_by.join('、')}</small>}</span>
          <Tag color={room.state === 'available' ? 'green' : room.state === 'occupied' ? 'red' : undefined}>{stateLabel[room.state]}</Tag>
        </label>)}
      </div>
    </section>}
    </>}
  </Modal>
}

function ViewAllocationPreview({ rooms }: { rooms: RoomResource[] }) {
  if (!rooms.length) return <div className="facility-view-allocation-empty">该规则暂无已回显的教室资源。</div>
  const capacity = rooms.reduce((total, room) => total + room.capacity, 0)
  const buildingCount = new Set(rooms.map((room) => room.building_name)).size
  return <>
    <div className="facility-capacity-summary is-ok" role="status">
      <div className="facility-capacity-result"><strong>资源分配已完成</strong><span>本规则已将以下场室分配给目标届别，空间资源可以在不同届别之间复用。</span></div>
      <div className="facility-capacity-metrics"><span>已分配容量 {capacity} 人</span><span>涉及教学楼 {buildingCount} 栋</span><span>已分配场室 {rooms.length} 间</span></div>
    </div>
    <section className="facility-room-preview" aria-label="已分配场室预览">
      <header className="facility-room-preview-head">
        <div><strong>教学楼场室分布</strong><span>绿色表示本规则已分配的场室。</span></div>
        <div className="facility-room-legend"><span className="is-available">已分配</span></div>
      </header>
      <div className="facility-room-grid">
        {rooms.map((room) => <div key={room.id} className="facility-room-option is-current">
          <span className="facility-room-option-copy"><strong>{room.building_name} · {room.floor}层 · {room.name}</strong><small>{room.code || '未设置编号'} · {room.capacity}人 · {room.room_type === 'classroom' ? '普通教室' : room.room_type}</small></span>
          <Tag color="green">已分配</Tag>
        </div>)}
      </div>
    </section>
  </>
}
