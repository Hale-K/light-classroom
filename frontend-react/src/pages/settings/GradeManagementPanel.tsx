import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { facilityApi, orgApi } from '@/api'
import type { Campus, Grade } from '@/types'

const levelNames: Record<number, string> = { 1: '高一年级', 2: '高二年级', 3: '高三年级' }

type GradeFormValues = { name: string; level: number; campus_id: number }

export default function GradeManagementPanel() {
  const { message } = App.useApp()
  const [grades, setGrades] = useState<Grade[]>([])
  const [campuses, setCampuses] = useState<Campus[]>([])
  const [campusId, setCampusId] = useState<number | undefined>()
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<GradeFormValues>()

  const load = async () => {
    setLoading(true)
    try {
      const [gradeRows, overview] = await Promise.all([orgApi.grades(), facilityApi.overview()])
      setGrades(gradeRows)
      setCampuses(overview.campuses)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '年级数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filteredGrades = useMemo(
    () => (campusId ? grades.filter((grade) => grade.campus_id === campusId) : grades),
    [campusId, grades],
  )

  const columns: ColumnsType<Grade> = [
    {
      title: '年级名称',
      dataIndex: 'name',
      key: 'name',
      render: (value: string) => <span style={{ whiteSpace: 'nowrap' }}>{value}</span>,
    },
    {
      title: '年级层级',
      dataIndex: 'level',
      key: 'level',
      render: (value: number) => <Tag color="blue">{levelNames[value] ?? `第${value}级`}</Tag>,
    },
    {
      title: '所属校区',
      dataIndex: 'campus_name',
      key: 'campus_name',
      render: (value: string | null | undefined) => value || <span style={{ color: '#98a2b3' }}>未关联校区</span>,
    },
    {
      title: '状态',
      key: 'status',
      render: () => <Tag color="green">已建立</Tag>,
    },
  ]

  const submit = async (values: GradeFormValues) => {
    try {
      await orgApi.createGrade(values)
      message.success('年级已保存')
      setOpen(false)
      form.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '年级保存失败')
    }
  }

  const closeModal = () => {
    setOpen(false)
    form.resetFields()
  }

  const campusOptions = campuses.map((campus) => ({ label: campus.name, value: campus.id }))

  return (
    <section className="stg-grade-panel">
      <div className="stg-grade-panel__header">
        <div>
          <h2>年级基础数据</h2>
          <p>按校区维护高一、高二、高三，年级部只关联这里的年级。</p>
        </div>
        <div className="stg-grade-panel__actions">
          <Select allowClear value={campusId} placeholder="全部校区" style={{ width: 180 }} onChange={setCampusId} options={campusOptions} />
          <Button onClick={() => void load()} loading={loading}>刷新</Button>
          <Button type="primary" onClick={() => setOpen(true)} disabled={!campuses.length}>新建年级</Button>
        </div>
      </div>
      <Table<Grade>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={filteredGrades}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: campuses.length ? '暂无年级数据，请新建年级' : '请先在空间资源中创建校区' }}
      />
      <Modal title="新建年级" open={open} centered onCancel={closeModal} onOk={() => form.submit()} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" onFinish={submit} initialValues={{ level: 1 }}>
          <Form.Item name="campus_id" label="所属校区" rules={[{ required: true, message: '请选择校区' }]}>
            <Select placeholder="请选择校区" options={campusOptions} />
          </Form.Item>
          <Form.Item name="level" label="年级层级" rules={[{ required: true, message: '请选择年级层级' }]}>
            <Select options={[1, 2, 3].map((level) => ({ label: levelNames[level], value: level }))} />
          </Form.Item>
          <Form.Item name="name" label="年级名称" rules={[{ required: true, message: '请输入年级名称' }]}>
            <Input placeholder="例如：高一年级" />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
