import { useEffect, useMemo, useState } from 'react'
import { App, Button, Checkbox, Form, Input, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { facilityApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'
import type { FacilityOverview, RoomResource } from '@/types'
import { hasRoomFeature } from '@/pages/campus-buildings/room-features'

const TYPE_LABEL: Record<RoomResource['room_type'], string> = { classroom: '普通教室', laboratory: '实验室', computer: '计算机房', meeting: '会议室', auditorium: '报告厅', office: '办公室' }
type RoomForm = Omit<RoomResource, 'id' | 'building_name' | 'status' | 'features'> & { multimedia?: boolean }

export default function RoomsView({ embedded = false }: { embedded?: boolean }) {
  const { message } = App.useApp()
  const [overview, setOverview] = useState<FacilityOverview>()
  const [rooms, setRooms] = useState<RoomResource[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [buildingId, setBuildingId] = useState<number>()
  const [roomType, setRoomType] = useState<RoomResource['room_type']>()
  const [form] = Form.useForm<RoomForm>()

  const load = async () => {
    setLoading(true)
    try { const [base, list] = await Promise.all([facilityApi.overview(), facilityApi.rooms()]); setOverview(base); setRooms(list) }
    catch (error) { message.error(error instanceof Error ? error.message : '加载场室失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  const filtered = useMemo(() => rooms.filter((item) => (!buildingId || item.building_id === buildingId) && (!roomType || item.room_type === roomType) && (!keyword.trim() || `${item.name}${item.code || ''}${item.building_name}`.toLowerCase().includes(keyword.trim().toLowerCase()))), [rooms, buildingId, roomType, keyword])

  const create = async (values: RoomForm) => {
    setSaving(true)
    try {
      await facilityApi.createRoom({ ...values, name: values.name.trim(), code: values.code?.trim() || undefined, features: values.multimedia ? ['multimedia'] : [] })
      setOpen(false); form.resetFields(); message.success('场室已创建'); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '创建场室失败') }
    finally { setSaving(false) }
  }
  const columns: ColumnsType<RoomResource> = [
    { title: '场室', dataIndex: 'name', render: (name, row) => <><strong>{name}</strong><div className="facility-cell-note">{row.building_name} · {row.floor} 层</div></> },
    { title: '类型', dataIndex: 'room_type', width: 120, render: (value) => TYPE_LABEL[value as RoomResource['room_type']] },
    { title: '容量', dataIndex: 'capacity', width: 90, render: (value) => `${value} 人` },
    { title: '设备与用途', key: 'uses', render: (_, row) => <Space size={[4, 4]} wrap>{hasRoomFeature(row.features, 'multimedia') && <Tag>多媒体</Tag>}{row.is_schedulable && <Tag color="blue">可排课</Tag>}{row.is_exam_enabled && <Tag color="gold">可排考</Tag>}{row.is_meeting_enabled && <Tag color="green">可开会</Tag>}</Space> },
    { title: '状态', dataIndex: 'status', width: 90, render: (value) => <span className="facility-status"><i />{value === 'available' ? '可用' : value}</span> },
  ]

  const createButton = <Button type="primary" disabled={!overview?.buildings.length} onClick={() => setOpen(true)}>新增场室</Button>
  return <div className={embedded ? 'facility-pane' : 'zh-page facility-page'}>
    {embedded ? <div className="facility-subhead"><div><h3>场室资源</h3><p>维护房间容量、设备和可排课、排考、会议等用途。</p></div>{createButton}</div> : <><PageHeader title="场室资源" extra={createButton} /><p className="zh-page-desc">统一维护教室、实验室、会议室和报告厅，并明确每个场室可参与的业务。</p></>}
    <FilterCard><div className="zh-filter-row"><Input allowClear value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索场室、编号或楼宇" style={{ width: 240 }} /><Select allowClear value={buildingId} onChange={setBuildingId} placeholder="全部楼宇" style={{ width: 180 }} options={overview?.buildings.map((item) => ({ label: item.name, value: item.id }))} /><Select allowClear value={roomType} onChange={setRoomType} placeholder="全部类型" style={{ width: 150 }} options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} /><span className="zh-filter-count">共 {filtered.length} 间</span></div></FilterCard>
    <TableCard><Table rowKey="id" columns={columns} dataSource={filtered} loading={loading} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 间` }} locale={{ emptyText: <EmptyState icon="grid" title="没有符合条件的场室" desc={overview?.buildings.length ? '新增场室或调整筛选条件。' : '请先在“校区与楼宇”中创建楼宇。'} height={240} /> }} /></TableCard>
    <Modal title="新增场室" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={saving} okText="创建" width={600}>
      <Form form={form} layout="vertical" requiredMark={false} onFinish={create} initialValues={{ floor: 1, capacity: 40, room_type: 'classroom', is_schedulable: true, is_exam_enabled: false, is_meeting_enabled: false }}>
        <div className="facility-form-grid"><Form.Item name="building_id" label="所属楼宇" rules={[{ required: true, message: '请选择楼宇' }]}><Select options={overview?.buildings.map((item) => ({ label: item.name, value: item.id }))} /></Form.Item><Form.Item name="room_type" label="场室类型" rules={[{ required: true }]}><Select options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item></div>
        <div className="facility-form-grid"><Form.Item name="name" label="场室名称" rules={[{ required: true, message: '请输入场室名称' }]}><Input placeholder="例如：高一（1）班教室" /></Form.Item><Form.Item name="code" label="场室编号"><Input placeholder="例如：A-201" /></Form.Item></div>
        <div className="facility-form-grid"><Form.Item name="floor" label="所在楼层"><InputNumber min={-5} max={100} style={{ width: '100%' }} /></Form.Item><Form.Item name="capacity" label="容纳人数"><InputNumber min={1} max={5000} style={{ width: '100%' }} /></Form.Item></div>
        <div className="facility-checks"><Form.Item name="multimedia" valuePropName="checked"><Checkbox>配备多媒体</Checkbox></Form.Item><Form.Item name="is_schedulable" valuePropName="checked"><Checkbox>可用于排课</Checkbox></Form.Item><Form.Item name="is_exam_enabled" valuePropName="checked"><Checkbox>可用于排考</Checkbox></Form.Item><Form.Item name="is_meeting_enabled" valuePropName="checked"><Checkbox>可用于会议</Checkbox></Form.Item></div>
      </Form>
    </Modal>
  </div>
}
