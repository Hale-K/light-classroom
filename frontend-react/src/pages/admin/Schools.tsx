import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { App, Button, Form, Input, Modal, Radio, Select, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import FilterCard from '@/components/FilterCard'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import { useAdminStore } from '@/store/admin'
import type { AdminSchool, GaokaoMode } from '@/types'
import { GAOKAO_MODE_DICT } from '@/types/dict'

interface CreateSchoolForm {
  code: string
  name: string
  province: string
  gaokao_mode: GaokaoMode
  admin_name: string
  admin_phone: string
  admin_password: string
}

interface EditSchoolForm {
  name: string
  province: string
  gaokao_mode: GaokaoMode
  admin_phone?: string
}

interface ResetForm {
  password: string
}

const gaokaoModeOptions: Array<{ value: GaokaoMode; label: string }> = [
  { value: '3+1+2', label: '新高考 3+1+2' },
  { value: '3+3', label: '新高考 3+3' },
  { value: 'traditional', label: '传统文理高考' },
]

const provinces = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海', '江苏',
  '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '广西',
  '海南', '重庆', '四川', '贵州', '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆',
]

const provinceOptions = provinces.map((p) => ({ value: p, label: p }))

const styles: Record<string, CSSProperties> = {
  pageDesc: { margin: '0 0 20px', fontSize: 13, color: 'var(--text-2)' },
  summary: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 14,
    width: 'fit-content',
    marginBottom: 16,
    padding: '16px 20px',
    border: '1px solid var(--border)',
    borderRadius: 10,
    background: 'var(--surface)',
  },
  summaryLabel: { fontSize: 12, color: 'var(--text-2)' },
  summaryValue: { fontSize: 24, fontWeight: 700, color: 'var(--ink)', fontVariantNumeric: 'tabular-nums' },
  summaryNote: { fontSize: 12, color: 'var(--text-3)' },
  filterWrap: { marginBottom: 16 },
  codeHint: { margin: '-8px 0 18px', fontSize: 12, color: 'var(--text-3)', lineHeight: 1.5 },
  resetTarget: {
    marginBottom: 16,
    padding: '10px 12px',
    border: '1px solid var(--border)',
    borderRadius: 8,
    background: 'var(--surface-2)',
    color: 'var(--text-1)',
    fontSize: 13,
    lineHeight: 1.6,
  },
}

export default function AdminSchools() {
  const { message } = App.useApp()
  const schools = useAdminStore((s) => s.schools)
  const loadSchools = useAdminStore((s) => s.loadSchools)
  const createSchool = useAdminStore((s) => s.createSchool)
  const updateSchool = useAdminStore((s) => s.updateSchool)
  const resetPassword = useAdminStore((s) => s.resetPassword)

  const [loading, setLoading] = useState(false)

  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createForm] = Form.useForm<CreateSchoolForm>()

  const [editOpen, setEditOpen] = useState(false)
  const [editingId, setEditingId] = useState(0)
  const [editingCode, setEditingCode] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [editForm] = Form.useForm<EditSchoolForm>()

  const [resetOpen, setResetOpen] = useState(false)
  const [resetId, setResetId] = useState(0)
  const [resetName, setResetName] = useState('')
  const [resetPhone, setResetPhone] = useState('')
  const [savingReset, setSavingReset] = useState(false)
  const [resetForm] = Form.useForm<ResetForm>()

  const fetchSchools = async () => {
    setLoading(true)
    try {
      await loadSchools()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学校列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSchools()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filteredSchools = useMemo(() => {
    const query = appliedKeyword.trim().toLowerCase()
    return schools.filter((item) => {
      if (!query) return true
      return (
        item.name.toLowerCase().includes(query) ||
        item.code.toLowerCase().includes(query) ||
        (item.province || '').toLowerCase().includes(query)
      )
    })
  }, [schools, appliedKeyword])

  const pagedSchools = useMemo(
    () => filteredSchools.slice((page - 1) * pageSize, page * pageSize),
    [filteredSchools, page, pageSize],
  )

  const handleSearch = () => {
    setAppliedKeyword(keyword)
    setPage(1)
  }

  const resetFilters = () => {
    setKeyword('')
    setAppliedKeyword('')
    setPage(1)
  }

  const openCreate = () => {
    createForm.resetFields()
    createForm.setFieldsValue({ gaokao_mode: '3+1+2' })
    setCreateOpen(true)
  }

  const onCreate = async (values: CreateSchoolForm) => {
    setCreating(true)
    try {
      await createSchool(values)
      setCreateOpen(false)
      message.success('学校已创建')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建学校失败')
    } finally {
      setCreating(false)
    }
  }

  const openEdit = (row: AdminSchool) => {
    editForm.setFieldsValue({
      name: row.name,
      province: row.province,
      gaokao_mode: row.gaokao_mode,
      admin_phone: row.admin_phone || '',
    })
    setEditingId(row.id)
    setEditingCode(row.code)
    setEditOpen(true)
  }

  const onSaveEdit = async (values: EditSchoolForm) => {
    setSavingEdit(true)
    try {
      await updateSchool(editingId, {
        name: values.name.trim(),
        province: values.province,
        gaokao_mode: values.gaokao_mode,
        admin_phone: values.admin_phone?.trim() || undefined,
      })
      setEditOpen(false)
      message.success('学校信息已更新')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSavingEdit(false)
    }
  }

  const openReset = (row: AdminSchool) => {
    resetForm.resetFields()
    setResetId(row.id)
    setResetName(row.name)
    setResetPhone(row.admin_phone || '')
    setResetOpen(true)
  }

  const onReset = async (values: ResetForm) => {
    setSavingReset(true)
    try {
      await resetPassword(resetId, values.password)
      setResetOpen(false)
      message.success('密码已重置')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重置失败')
    } finally {
      setSavingReset(false)
    }
  }

  const columns: ColumnsType<AdminSchool> = [
    { title: '学校名称', dataIndex: 'name', key: 'name', minWidth: 200 },
    { title: '学校代码', dataIndex: 'code', key: 'code', width: 150 },
    { title: '省份', dataIndex: 'province', key: 'province', width: 100 },
    {
      title: '高考模式',
      dataIndex: 'gaokao_mode',
      key: 'gaokao_mode',
      width: 140,
      render: (value) => <DictTag dict={GAOKAO_MODE_DICT} value={value} />,
    },
    { title: '类型', dataIndex: 'type', key: 'type', width: 130 },
    {
      title: '管理员电话',
      dataIndex: 'admin_phone',
      key: 'admin_phone',
      minWidth: 150,
      render: (value) => value || '—',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      minWidth: 170,
      render: (value) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      fixed: 'right',
      render: (_, row) => (
        <>
          <Button type="link" size="small" style={{ paddingInline: 6 }} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            style={{ paddingInline: 6, color: 'var(--yellow-ink)' }}
            onClick={() => openReset(row)}
          >
            重置密码
          </Button>
        </>
      ),
    },
  ]

  return (
    <div className="page-shell page-enter">
      <PageHeader
        title={
          <span style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: '0.5px',
                textTransform: 'uppercase',
                color: 'var(--text-3)',
              }}
            >
              TENANT DIRECTORY
            </span>
            <span>学校管理</span>
          </span>
        }
        extra={
          <Button type="primary" onClick={openCreate}>
            新增学校
          </Button>
        }
      />
      <p style={styles.pageDesc}>创建和维护接入轻课堂的学校工作区。</p>

      <div style={styles.summary}>
        <span style={styles.summaryLabel}>当前学校总数</span>
        <strong style={styles.summaryValue}>{schools.length}</strong>
        <span style={styles.summaryNote}>已接入平台的学校工作区</span>
      </div>

      <TableCard
        title="学校目录"
        extra={
          <Button type="link" size="small" onClick={fetchSchools}>
            刷新
          </Button>
        }
      >
        <div style={styles.filterWrap}>
          <FilterCard>
            <div className="zh-filter-row">
              <label className="zh-filter-field">
                <span>学校</span>
                <Input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  allowClear
                  placeholder="名称 / 代码 / 省份"
                  style={{ width: 240 }}
                />
              </label>
              <Button type="primary" onClick={handleSearch}>
                查询
              </Button>
              <Button onClick={resetFilters}>重置</Button>
              <span className="zh-filter-count">当前 {filteredSchools.length} 所</span>
            </div>
          </FilterCard>
        </div>
        <Table<AdminSchool>
          rowKey="id"
          columns={columns}
          dataSource={pagedSchools}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: filteredSchools.length,
            onChange: (p, s) => {
              setPage(p)
              setPageSize(s)
            },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 所`,
          }}
          scroll={{ x: 1080 }}
          locale={{
            emptyText: (
              <EmptyState
                icon="users"
                title="暂无学校"
                desc="点击右上角「新增学校」创建第一个学校工作区"
                height={240}
              />
            ),
          }}
        />
      </TableCard>

      <Modal
        title="新增学校"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={creating}
        okText="创建学校"
        cancelText="取消"
        width={460}
      >
        <Form<CreateSchoolForm> form={createForm} layout="vertical" requiredMark={false} onFinish={onCreate}>
          <Form.Item name="name" label="学校名称" rules={[{ required: true, message: '请输入学校名称' }]}>
            <Input placeholder="例如：衡川实验中学" />
          </Form.Item>
          <Form.Item name="code" label="学校代码" rules={[{ required: true, message: '请输入学校代码' }]}>
            <Input placeholder="例如：hengchuan" />
          </Form.Item>
          <Form.Item name="province" label="学校所在省份" rules={[{ required: true, message: '请选择省份' }]}>
            <Select showSearch placeholder="请选择省份" options={provinceOptions} />
          </Form.Item>
          <Form.Item name="gaokao_mode" label="默认高考模式" rules={[{ required: true, message: '请选择高考模式' }]}>
            <Radio.Group optionType="button" buttonStyle="outline">
              {gaokaoModeOptions.map((o) => (
                <Radio.Button key={o.value} value={o.value}>
                  {o.label}
                </Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>
          <div style={styles.codeHint}>新建届别方案时继承该模式，之后可按入学年份单独调整。</div>
          <Form.Item name="admin_name" label="管理员姓名" rules={[{ required: true, message: '请输入管理员姓名' }]}>
            <Input placeholder="校长姓名" />
          </Form.Item>
          <Form.Item name="admin_phone" label="管理员电话">
            <Input placeholder="校长登录手机号" />
          </Form.Item>
          <Form.Item
            name="admin_password"
            label="初始密码"
            rules={[
              { required: true, message: '请输入初始密码' },
              { min: 6, message: '至少 6 位' },
            ]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑学校"
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={() => editForm.submit()}
        confirmLoading={savingEdit}
        okText="保存"
        cancelText="取消"
        width={420}
      >
        <Form<EditSchoolForm> form={editForm} layout="vertical" requiredMark={false} onFinish={onSaveEdit}>
          <Form.Item name="name" label="学校名称" rules={[{ required: true, message: '请输入学校名称' }]}>
            <Input placeholder="请输入学校名称" />
          </Form.Item>
          <Form.Item name="province" label="学校所在省份" rules={[{ required: true, message: '请选择省份' }]}>
            <Select showSearch options={provinceOptions} />
          </Form.Item>
          <Form.Item name="gaokao_mode" label="默认高考模式" rules={[{ required: true, message: '请选择高考模式' }]}>
            <Select options={gaokaoModeOptions} />
          </Form.Item>
          <div style={styles.codeHint}>修改后影响新建届别；已存在的届别方案保持原模式，可单独修改。</div>
          <Form.Item name="admin_phone" label="管理员手机号">
            <Input placeholder="校长登录账号" />
          </Form.Item>
          <div style={styles.codeHint}>仅变更校长登录手机号；超管身份与密码保持不变</div>
          <Form.Item label="学校代码">
            <Input value={editingCode} disabled placeholder="学校代码不可修改" />
          </Form.Item>
          <div style={styles.codeHint}>学校代码作为系统标识，创建后不可修改</div>
        </Form>
      </Modal>

      <Modal
        title="重置密码"
        open={resetOpen}
        onCancel={() => setResetOpen(false)}
        onOk={() => resetForm.submit()}
        confirmLoading={savingReset}
        okText="确认重置"
        cancelText="取消"
        width={400}
      >
        <Form<ResetForm> form={resetForm} layout="vertical" requiredMark={false} onFinish={onReset}>
          <div style={styles.resetTarget}>
            为「{resetName}」{resetPhone ? `（校长 ${resetPhone}）` : ''} 设置新登录密码
          </div>
          <Form.Item
            name="password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '至少 6 位' },
            ]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}