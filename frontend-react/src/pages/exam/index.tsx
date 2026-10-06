import { useEffect, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { examApi } from '@/api'
import type { Exam } from '@/types'
import { EXAM_STATUS_DICT, EXAM_TYPE_DICT } from '@/types/dict'

export default function ExamManage() {
  const { message } = App.useApp()
  const [exams, setExams] = useState<Exam[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', exam_type: 'monthly', academic_year: '', term: '1' })

  const loadExams = async () => {
    setLoading(true)
    try {
      setExams(await examApi.list())
    } catch (error) {
      message.error(error instanceof Error ? error.message : '考试列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadExams() }, [])

  const createExam = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await examApi.create({ ...form, name: form.name.trim() })
      message.success('考试已创建')
      setOpen(false)
      await loadExams()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '考试创建失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<Exam> = [
    { title: '考试名称', dataIndex: 'name' },
    { title: '学年', dataIndex: 'academic_year', width: 140, render: (value) => value || '—' },
    { title: '类型', dataIndex: 'exam_type', width: 120, render: (value) => EXAM_TYPE_DICT[value || 'other']?.label || '其他' },
    { title: '状态', dataIndex: 'status', width: 120, render: (value) => <Tag color={EXAM_STATUS_DICT[value]?.color}>{EXAM_STATUS_DICT[value]?.label || value}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 180, render: (value) => value ? new Date(value).toLocaleDateString() : '—' },
  ]

  return (
    <div className="zh-page">
      <div className="zh-page-header">
        <div><h1>考试管理</h1><p>维护考试基本信息；考试日期、场次、考场和监考安排在排考管理中完成。</p></div>
        <Button type="primary" onClick={() => {
          const year = new Date().getFullYear()
          setForm({ name: '', exam_type: 'monthly', academic_year: `${year}-${year + 1}`, term: '1' })
          setOpen(true)
        }}>新建考试</Button>
      </div>

      <Table rowKey="id" loading={loading} columns={columns} dataSource={exams} pagination={{ pageSize: 10, showSizeChanger: false }} />

      <Modal title="新建考试" open={open} onCancel={() => setOpen(false)} onOk={createExam} okText="创建" cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !form.name.trim() }}>
        <Form layout="vertical">
          <Form.Item label="考试名称" required><Input autoFocus maxLength={100} value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} placeholder="如：高一上学期期中考试" /></Form.Item>
          <Form.Item label="考试类型"><Select value={form.exam_type} onChange={(exam_type) => setForm((value) => ({ ...value, exam_type }))} options={Object.entries(EXAM_TYPE_DICT).map(([value, item]) => ({ value, label: item.label }))} /></Form.Item>
          <Form.Item label="学年"><Input maxLength={20} value={form.academic_year} onChange={(event) => setForm((value) => ({ ...value, academic_year: event.target.value }))} placeholder="如：2026-2027" /></Form.Item>
          <Form.Item label="学期"><Select value={form.term} onChange={(term) => setForm((value) => ({ ...value, term }))} options={[{ value: '1', label: '第一学期' }, { value: '2', label: '第二学期' }]} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
