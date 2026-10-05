import { useEffect, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Switch, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { schedulingApi } from '@/api'
import type { SubjectInfo } from '@/types'
import { assertSubjectTaskSubmission } from '@/assistant/subjectTask'
import './index.css'

type SubjectFormValues = {
  name: string
  course_type: 'subject' | 'activity'
  evening_study_allowed: boolean
}

export default function SubjectManagementView() {
  const { message } = App.useApp()
  const [subjects, setSubjects] = useState<SubjectInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<SubjectInfo | null>(null)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [form] = Form.useForm<SubjectFormValues>()

  const load = async () => {
    setLoading(true)
    try {
      setSubjects(await schedulingApi.subjects())
      setLoaded(true)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '科目加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const filtered = keyword.trim()
    ? subjects.filter((s) => s.name.includes(keyword.trim()))
    : subjects

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ course_type: 'subject', evening_study_allowed: false })
    setOpen(true)
  }

  const openEdit = (subject: SubjectInfo) => {
    if (subject.tenant_id == null) return
    setEditing(subject)
    form.setFieldsValue({ name: subject.name, course_type: subject.course_type || 'subject', evening_study_allowed: Boolean(subject.evening_study_allowed) })
    setOpen(true)
  }

  const close = () => {
    setOpen(false)
    setEditing(null)
    form.resetFields()
  }

  const submit = async (values: SubjectFormValues) => {
    setSaving(true)
    try {
      assertSubjectTaskSubmission(values, Boolean(editing))
      if (editing) {
        await schedulingApi.updateSubject(editing.id, values)
        message.success('科目已更新')
      } else {
        await schedulingApi.createSubject(values.name.trim(), values.evening_study_allowed, values.course_type)
        message.success('科目已保存')
      }
      close()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '科目保存失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<SubjectInfo> = [
    { title: '科目名称', dataIndex: 'name', key: 'name', render: (value: string) => <strong>{value}</strong> },
    {
      title: '类型', key: 'course_type', width: 120,
      render: (_, row) => row.course_type === 'activity' ? <Tag color="purple">活动课</Tag> : <Tag color="blue">学科课</Tag>,
    },
    {
      title: '来源', key: 'source', width: 150,
      render: (_, row) => row.tenant_id == null ? <Tag color="blue">系统公共</Tag> : <Tag color="green">本校自定义</Tag>,
    },
    {
      title: '晚自习', key: 'evening_study_allowed', width: 150,
      render: (_, row) => row.evening_study_allowed ? <Tag color="green">允许安排</Tag> : <Tag>不安排</Tag>,
    },
    {
      title: '操作', key: 'actions', width: 120,
      render: (_, row) => row.tenant_id == null
        ? <span className="subject-muted">公共科目不可编辑</span>
        : <Button type="link" onClick={() => openEdit(row)}>编辑</Button>,
    },
  ]

  return (
    <section className="subject-page" data-subject-page-ready={loaded && !loading}>
      <div className="subject-hero">
        <div>
          <div className="subject-kicker">基础资料 / SUBJECTS</div>
          <h1>科目管理</h1>
          <p>维护本校排课、任教关系和晚自习会使用的科目。系统公共科目可直接使用，本校自定义科目只对当前学校生效。</p>
        </div>
        <div className="subject-actions">
          <Input.Search
            allowClear
            placeholder="搜索科目名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onSearch={setKeyword}
            style={{ width: 220 }}
          />
          <Button onClick={() => void load()} loading={loading}>刷新</Button>
          <Button type="primary" data-subject-create onClick={openCreate}>新增科目</Button>
        </div>
      </div>
      <div className="subject-surface">
        <Table<SubjectInfo> rowKey="id" loading={loading} columns={columns} dataSource={filtered}
          pagination={{
            current: page,
            pageSize,
            total: filtered.length,
            onChange: (p, s) => { setPage(p); setPageSize(s) },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个`,
          }}
          locale={{ emptyText: '暂无科目，请新增本校科目' }}
        />
      </div>
      <Modal className="subject-agent-form" title={editing ? '编辑本校科目' : '新增本校科目'} open={open} centered onCancel={close} onOk={() => form.submit()} okText="保存" cancelText="取消" confirmLoading={saving}>
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="name" label="科目名称" rules={[{ required: true, whitespace: true, message: '请输入科目名称' }, { max: 20, message: '科目名称不能超过 20 个字' }]}>
            <Input placeholder="例如：校本课程、心理" autoFocus />
          </Form.Item>
          <Form.Item name="course_type" label="课程类型" rules={[{ required: true }]} extra="学科课参与教师课量统计；活动课可不绑定教师，班会会自动使用本班班主任。">
            <Select classNames={{ popup: { root: 'subject-agent-options' } }} options={[{ value: 'subject', label: '学科课' }, { value: 'activity', label: '活动课' }]} />
          </Form.Item>
          <Form.Item name="evening_study_allowed" label="晚自习资格" valuePropName="checked" extra="这里只定义该科目是否可以被晚自习排课使用，不配置晚自习节数。">
            <Switch checkedChildren="允许" unCheckedChildren="不允许" />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
