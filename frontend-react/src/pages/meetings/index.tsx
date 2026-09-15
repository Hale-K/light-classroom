import { useEffect, useMemo, useState } from 'react'
import { App, Button, DatePicker, Form, Input, Modal, Select, Table, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { Dayjs } from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { facilityApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'
import SelectEmptyGuide from '@/components/SelectEmptyGuide'
import type { MeetingRecord, RoomResource } from '@/types'

type MeetingForm = { title: string; room_id: number; period: [Dayjs, Dayjs]; agenda?: string }

export default function MeetingsView() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [meetings, setMeetings] = useState<MeetingRecord[]>([])
  const [rooms, setRooms] = useState<RoomResource[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<MeetingForm>()
  const meetingRooms = useMemo(() => rooms.filter((room) => room.is_meeting_enabled && room.status === 'available'), [rooms])

  const load = async () => {
    setLoading(true)
    try { const [items, allRooms] = await Promise.all([facilityApi.meetings(), facilityApi.rooms()]); setMeetings(items); setRooms(allRooms) }
    catch (error) { message.error(error instanceof Error ? error.message : '加载会议失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  const create = async (values: MeetingForm) => {
    setSaving(true)
    try {
      await facilityApi.createMeeting({ title: values.title.trim(), room_id: values.room_id, start_at: values.period[0].format('YYYY-MM-DDTHH:mm:ss'), end_at: values.period[1].format('YYYY-MM-DDTHH:mm:ss'), agenda: values.agenda?.trim() || undefined, participant_ids: [] })
      setOpen(false); form.resetFields(); message.success('会议已安排'); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '安排会议失败') }
    finally { setSaving(false) }
  }
  const columns: ColumnsType<MeetingRecord> = [
    { title: '会议', dataIndex: 'title', render: (title, row) => <><strong>{title}</strong><div className="facility-cell-note">{row.agenda || '未填写议题说明'}</div></> },
    { title: '场室', dataIndex: 'room_name', width: 180 },
    { title: '开始时间', dataIndex: 'start_at', width: 170, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    { title: '结束时间', dataIndex: 'end_at', width: 170, render: (value) => dayjs(value).format('YYYY-MM-DD HH:mm') },
    { title: '状态', dataIndex: 'status', width: 100, render: () => <Tag color="blue">已安排</Tag> },
  ]

  return <div className="zh-page facility-page">
    <PageHeader title="会议管理" extra={<Button type="primary" disabled={!meetingRooms.length} onClick={() => setOpen(true)}>安排会议</Button>} />
    <p className="zh-page-desc">选择已开放会议用途的场室；时间冲突由系统统一校验，不允许重复占用。</p>
    {!meetingRooms.length && <div className="facility-notice"><strong>还没有可预约会议室</strong><span>请先在“场室资源”中创建场室，并启用“可用于会议”。</span><Button type="link" onClick={() => navigate('/campus-buildings?tab=rooms')}>去场室资源设置</Button></div>}
    <TableCard title="会议日程"><Table rowKey="id" columns={columns} dataSource={meetings} loading={loading} pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 场` }} locale={{ emptyText: <EmptyState icon="calendar" title="暂无会议安排" desc="会议会按开始时间展示，并占用对应场室。" height={260} /> }} /></TableCard>
    <Modal title="安排会议" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={saving} okText="确认安排" width={560}>
      <Form form={form} layout="vertical" requiredMark={false} onFinish={create}>
        <Form.Item name="title" label="会议名称" rules={[{ required: true, message: '请输入会议名称' }]}><Input placeholder="例如：高二年级教学工作会" /></Form.Item>
        <Form.Item name="room_id" label="会议室" rules={[{ required: true, message: '请选择会议室' }]}><Select options={meetingRooms.map((room) => ({ label: `${room.building_name} · ${room.name}（${room.capacity}人）`, value: room.id }))} notFoundContent={<SelectEmptyGuide description="暂无可预约会议室" path="/campus-buildings?tab=rooms" actionLabel="去场室资源设置" compact />} /></Form.Item>
        <Form.Item name="period" label="会议时间" rules={[{ required: true, message: '请选择开始和结束时间' }]}><DatePicker.RangePicker showTime format="YYYY-MM-DD HH:mm" minuteStep={5} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="agenda" label="议题说明"><Input.TextArea rows={4} maxLength={2000} showCount placeholder="简要说明会议事项（选填）" /></Form.Item>
      </Form>
    </Modal>
  </div>
}
