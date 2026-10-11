import { translate as t, useLocale } from '@/i18n'
import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { facilityApi, orgApi } from '@/api'
import type { Campus, Grade } from '@/types'

const levelNames: Record<number, string> = { 1: '高一年级', 2: '高二年级', 3: '高三年级' }

type GradeFormValues = { name: string; level: number; campus_id?: number }

export default function GradeManagementPanel() {
  const locale = useLocale()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [grades, setGrades] = useState<Grade[]>([])
  const [campuses, setCampuses] = useState<Campus[]>([])
  const [campusId, setCampusId] = useState<number | undefined>()
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Grade | null>(null)
  const [form] = Form.useForm<GradeFormValues>()

  const load = async () => {
    setLoading(true)
    try {
      const [gradeRows, overview] = await Promise.all([orgApi.grades(), facilityApi.overview()])
      setGrades(gradeRows)
      setCampuses(overview.campuses)
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("年级数据加载失败"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filteredGrades = useMemo(
    () => (campusId ? grades.filter((grade) => grade.campus_id === campusId) : grades),
    [campusId, grades, locale],
  )

  const columns: ColumnsType<Grade> = [
    {
      title: t("年级名称"),
      dataIndex: 'name',
      key: 'name',
      render: (value: string) => <span style={{ whiteSpace: 'nowrap' }}>{value}</span>,
    },
    {
      title: t("年级层级"),
      dataIndex: 'level',
      key: 'level',
      render: (value: number) => <Tag color="blue">{levelNames[value] ?? t("第{{p0}}级", { p0: value })}</Tag>,
    },
    {
      title: t("所属校区"),
      dataIndex: 'campus_name',
      key: 'campus_name',
      render: (value: string | null | undefined) => value || <span style={{ color: '#98a2b3' }}>{t("未关联校区")}</span>,
    },
    {
      title: t("状态"),
      key: 'status',
      render: () => <Tag color="green">{t("已建立")}</Tag>,
    },
    {
      title: t("操作"),
      key: 'actions',
      align: 'right',
      render: (_, grade) => (
        <Button type="link" size="small" onClick={() => {
          setEditing(grade)
          form.setFieldsValue({ name: grade.name, level: grade.level, campus_id: grade.campus_id ?? undefined })
          setOpen(true)
        }}>{t("编辑")}</Button>
      ),
    },
  ]

  const submit = async (values: GradeFormValues) => {
    try {
      if (editing) await orgApi.updateGrade(editing.id, { ...values, campus_id: values.campus_id ?? null })
      else await orgApi.createGrade({ ...values, campus_id: values.campus_id ?? null })
      message.success(editing ? t("年级信息已更新") : t("年级已保存，校区可以稍后关联"))
      setOpen(false)
      setEditing(null)
      form.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("年级保存失败"))
    }
  }

  const closeModal = () => {
    setOpen(false)
    setEditing(null)
    form.resetFields()
  }

  const campusOptions = campuses.map((campus) => ({ label: campus.name, value: campus.id }))

  return (
    <section className="stg-grade-panel">
      <div className="stg-grade-panel__header">
        <div>
          <h2>{t("年级基础数据")}</h2>
          <p>{t("先建立高一、高二、高三；校区可以现在选择，也可以在空间准备好后补充。")}</p>
        </div>
        <div className="stg-grade-panel__actions">
          <Select allowClear value={campusId} placeholder={t("全部校区")} style={{ width: 180 }} onChange={setCampusId} options={campusOptions} />
          <Button onClick={() => void load()} loading={loading}>{t("刷新")}</Button>
          <Button type="primary" onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>{t("新建年级")}</Button>
        </div>
      </div>
      {!campuses.length && (
        <Alert
          type="info"
          showIcon
          message={t("当前还没有校区，仍可先建立年级")}
          description={<Space>{t("年级会显示为“未关联校区”。创建校区后回到这里编辑关联即可。")}<Button type="link" onClick={() => navigate('/campus-buildings?tab=resources')}>{t("去创建校区")}</Button></Space>}
        />
      )}
      <Table<Grade>
        rowKey="id"
        size="middle"
        loading={loading}
        columns={columns}
        dataSource={filteredGrades}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: t("暂无年级数据，可以直接新建年级") }}
      />
      <Modal title={editing ? t("编辑年级") : t("新建年级")} open={open} centered onCancel={closeModal} onOk={() => form.submit()} okText={t("保存")} cancelText={t("取消")}>
        <Form form={form} layout="vertical" onFinish={submit} initialValues={{ level: 1 }}>
          <Form.Item name="campus_id" label={t("所属校区")} extra={t("可选。没有校区时先保存年级，后续再编辑关联。")}>
            <Select allowClear placeholder={t("暂不关联校区")} options={campusOptions} />
          </Form.Item>
          <Form.Item name="level" label={t("年级层级")} rules={[{ required: true, message: t("请选择年级层级") }]}>
            <Select options={[1, 2, 3].map((level) => ({ label: levelNames[level], value: level }))} />
          </Form.Item>
          <Form.Item name="name" label={t("年级名称")} rules={[{ required: true, message: t("请输入年级名称") }]}>
            <Input placeholder={t("例如：高一年级")} />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  )
}
