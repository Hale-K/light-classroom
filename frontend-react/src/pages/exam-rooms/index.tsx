import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, InputNumber, Modal, Select, Spin, Table } from 'antd'
import { examSchedulingApi } from '@/api'
import type { ExamRoomEntry } from '@/types'
import PageHeader from '@/components/PageHeader'
import ExamModuleNav from '@/pages/exam-scheduling/ModuleNav'
import '@/pages/exam-scheduling/index.css'

const ROOM_TYPE_LABEL = { standard: '普通考场', special: '特殊考场', reserve: '备用考场' }
const ROOM_STATUS_LABEL = { available: '可用', maintenance: '维护中', disabled: '已停用' }
interface RoomFormValues { name: string; capacity: number; building?: string; room_type: keyof typeof ROOM_TYPE_LABEL; status: keyof typeof ROOM_STATUS_LABEL }

export default function ExamRoomsView() {
  const { message, modal } = App.useApp()
  const [form] = Form.useForm<RoomFormValues>()
  const [loading, setLoading] = useState(false)
  const [rooms, setRooms] = useState<ExamRoomEntry[]>([])
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>()
  const [typeFilter, setTypeFilter] = useState<string>()
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingRoom, setEditingRoom] = useState<ExamRoomEntry>()

  const load = async () => {
    setLoading(true)
    try { setRooms((await examSchedulingApi.rooms({ page: 1, page_size: 300 })).items) }
    catch (error) { message.error(error instanceof Error ? error.message : '考场加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const value = keyword.trim().toLowerCase()
    return rooms.filter((room) => (!value || `${room.name} ${room.building || ''}`.toLowerCase().includes(value)) && (!statusFilter || room.status === statusFilter) && (!typeFilter || room.room_type === typeFilter))
  }, [keyword, rooms, statusFilter, typeFilter])

  const openEditor = (room?: ExamRoomEntry) => {
    setEditingRoom(room)
    form.setFieldsValue(room ? { name: room.name, capacity: room.capacity, building: room.building || '', room_type: room.room_type, status: room.status } : { name: '', capacity: 40, building: '', room_type: 'standard', status: 'available' })
    setEditorOpen(true)
  }

  const save = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      if (editingRoom) await examSchedulingApi.updateRoom(editingRoom.id, values)
      else await examSchedulingApi.createRoom(values)
      await load()
      setEditorOpen(false)
      message.success(editingRoom ? '考场已修改' : '考场已创建')
    } catch (error) { message.error(error instanceof Error ? error.message : '考场保存失败') }
    finally { setLoading(false) }
  }

  const remove = (room: ExamRoomEntry) => modal.confirm({
    title: '删除考场', content: `确定删除“${room.name}”吗？`, okText: '确认删除', okButtonProps: { danger: true }, cancelText: '取消',
    onOk: async () => { await examSchedulingApi.deleteRoom(room.id); setRooms((rows) => rows.filter((item) => item.id !== room.id)); message.success('考场已删除') },
  })

  const columns = [
    { title: '考场名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'room_type', width: 120, render: (value: ExamRoomEntry['room_type']) => ROOM_TYPE_LABEL[value] },
    { title: '位置 / 楼栋', dataIndex: 'building', render: (value?: string) => value || '未填写' },
    { title: '座位容量', dataIndex: 'capacity', width: 110 },
    { title: '状态', dataIndex: 'status', width: 100, render: (value: ExamRoomEntry['status']) => <span className={`es-status es-status-${value}`}>{ROOM_STATUS_LABEL[value]}</span> },
    { title: '来源', width: 120, render: (_: unknown, row: ExamRoomEntry) => row.source_class_id ? '行政班教室' : '手动创建' },
    { title: '操作', width: 140, render: (_: unknown, row: ExamRoomEntry) => <><Button type="link" onClick={() => openEditor(row)}>修改</Button><Button type="link" danger onClick={() => remove(row)}>删除</Button></> },
  ]

  return <Spin spinning={loading}><div className="es-page">
    <PageHeader title="考场管理" extra={<Button type="primary" onClick={() => openEditor()}>新建考场</Button>} />
    <p className="zh-page-desc">这里只维护学校可用的考场资源，不处理任何排考任务。</p>
    <ExamModuleNav />
    <section className="es-room-manager">
      <header className="es-room-head"><div><span>学校基础资源</span><h2>可用考场清单</h2></div><div className="es-room-totals"><strong>{rooms.length}</strong><span>间考场</span><strong>{rooms.reduce((sum, room) => sum + room.capacity, 0)}</strong><span>个座位</span></div></header>
      <div className="es-room-tools"><Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索考场名称或楼栋" /><Select allowClear value={statusFilter} onChange={setStatusFilter} placeholder="全部状态" options={Object.entries(ROOM_STATUS_LABEL).map(([value, label]) => ({ value, label }))} /><Select allowClear value={typeFilter} onChange={setTypeFilter} placeholder="全部类型" options={Object.entries(ROOM_TYPE_LABEL).map(([value, label]) => ({ value, label }))} /><Button type="primary" onClick={() => openEditor()}>新建考场</Button></div>
      <Table rowKey="id" columns={columns} dataSource={filtered} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 间` }} />
    </section>
    <Modal title={editingRoom ? '修改考场' : '新建考场'} open={editorOpen} onCancel={() => setEditorOpen(false)} onOk={save} okText="保存" cancelText="取消" forceRender>
      <Form form={form} layout="vertical"><Form.Item label="考场名称" name="name" rules={[{ required: true, message: '请输入考场名称' }]}><Input /></Form.Item><div className="es-room-form-grid"><Form.Item label="座位容量" name="capacity" rules={[{ required: true }]}><InputNumber min={1} max={500} /></Form.Item><Form.Item label="考场类型" name="room_type"><Select options={Object.entries(ROOM_TYPE_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item></div><div className="es-room-form-grid"><Form.Item label="资源状态" name="status"><Select options={Object.entries(ROOM_STATUS_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item label="位置 / 楼栋" name="building"><Input /></Form.Item></div></Form>
    </Modal>
  </div></Spin>
}
