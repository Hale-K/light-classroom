import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, Modal, Popconfirm, Select, Switch, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { staffApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'
import type { StaffAccount } from '@/types'

interface AccountFormValues { name: string; phone: string; password: string }

export default function StaffAccountsView({ embedded = false }: { embedded?: boolean }) {
  const { message } = App.useApp()
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<'active' | 'disabled' | ''>('')
  const [form] = Form.useForm<AccountFormValues>()
  const [freezeForm] = Form.useForm<{ reason: string }>()
  const [freezeTarget, setFreezeTarget] = useState<StaffAccount | null>(null)

  const load = async () => {
    setLoading(true)
    try { setAccounts((await staffApi.list()).accounts) }
    catch (error) { message.error(error instanceof Error ? error.message : '人员账号加载失败') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return accounts.filter((item) =>
      (!query || item.name.toLowerCase().includes(query) || item.phone.includes(query)) &&
      (!status || item.status === status),
    )
  }, [accounts, keyword, status])

  const create = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSaving(true)
    try {
      await staffApi.create({ ...values, roles: [] })
      message.success('人员账号已创建，可继续分配岗位与权限')
      setOpen(false)
      form.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '账号创建失败')
    } finally { setSaving(false) }
  }

  const toggle = async (account: StaffAccount, checked: boolean) => {
    try {
      await staffApi.updateStatus(account.id, checked ? 'active' : 'disabled')
      await load()
      message.success(checked ? '账号已启用' : '账号已停用')
    } catch (error) { message.error(error instanceof Error ? error.message : '状态更新失败') }
  }

  const confirmFreeze = async () => {
    const values = await freezeForm.validateFields().catch(() => null)
    if (!values || !freezeTarget) return
    setSaving(true)
    try {
      await staffApi.freeze(freezeTarget.id, values.reason.trim())
      message.success(`已冻结 ${freezeTarget.name}`)
      setFreezeTarget(null)
      freezeForm.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '冻结失败')
    } finally { setSaving(false) }
  }

  const unfreeze = async (account: StaffAccount) => {
    try {
      await staffApi.unfreeze(account.id)
      message.success(`已解冻 ${account.name}`)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '解冻失败') }
  }

  const columns: TableProps<StaffAccount>['columns'] = [
    { title: '姓名', dataIndex: 'name', width: 180, render: (name, item) => (
      <div className="zh-person-cell">
        <strong>{name}</strong>
        <span>{item.is_school_admin ? '校长账号' : '教职工账号'}</span>
        {item.frozen && <Tag color="red" style={{ marginLeft: 8 }}>已冻结</Tag>}
      </div>
    ) },
    { title: '登录手机号', dataIndex: 'phone', width: 200 },
    { title: '岗位配置', key: 'roles', render: (_, item) => (
      <span className={item.roles.length ? 'zh-account-configured' : 'zh-account-pending'}>
        {item.is_school_admin ? '校长管理员' : item.roles.length ? `已配置 ${item.roles.length} 项职责` : '等待分配岗位'}
      </span>
    ) },
    { title: '冻结原因', dataIndex: 'freeze_reason', width: 200, render: (reason: string | null | undefined) => (
      reason ? <span className="zh-freeze-reason">{reason}</span> : <span style={{ color: 'rgba(0,0,0,.25)' }}>—</span>
    ) },
    { title: '账号状态', key: 'status', width: 130, render: (_, item) => (
      <Switch checked={item.status === 'active'} disabled={item.is_school_admin}
        checkedChildren="启用" unCheckedChildren="停用" onChange={(checked) => void toggle(item, checked)} />
    ) },
    {
      title: '操作', key: 'action', width: 160, render: (_, item) => item.is_school_admin ? null : item.frozen ? (
        <Popconfirm title="确认解冻该账号？" okText="解冻" cancelText="取消" onConfirm={() => void unfreeze(item)}>
          <Button type="link" size="small">解冻</Button>
        </Popconfirm>
      ) : (
        <Button type="link" size="small" danger onClick={() => { setFreezeTarget(item); freezeForm.resetFields() }}>
          冻结
        </Button>
      ),
    },
  ]

  const createButton = <Button type="primary" onClick={() => setOpen(true)}>新增人员账号</Button>
  return <div className={embedded ? 'personnel-pane' : 'zh-page'}>
    {embedded ? <div className="facility-subhead"><div><h3>人员账号</h3><p>建立教职工登录身份，再分配岗位和业务权限。</p></div>{createButton}</div> : <><PageHeader title="人员账号" extra={createButton} /><p className="zh-page-desc">先建立教职工登录账号，再到“岗位与权限”中安排其组织岗位和系统职责。</p></>}
    <FilterCard><div className="zh-filter-row">
      <label className="zh-filter-field"><span>人员</span><Input value={keyword} allowClear
        placeholder="姓名或手机号" onChange={(event) => setKeyword(event.target.value)} style={{ width: 240 }} /></label>
      <label className="zh-filter-field"><span>状态</span><Select value={status || undefined} allowClear
        placeholder="全部状态" onChange={(value) => setStatus(value ?? '')} style={{ width: 140 }}
        options={[{ label: '启用', value: 'active' }, { label: '停用', value: 'disabled' }]} /></label>
      <Button onClick={() => { setKeyword(''); setStatus('') }}>重置</Button>
      <span className="zh-filter-count">共 {filtered.length} 个账号</span>
    </div></FilterCard>
    <TableCard><Table rowKey="id" columns={columns} dataSource={filtered} loading={loading}
      pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }}
      locale={{ emptyText: <EmptyState height={240} title="暂无人员账号" desc="先创建教职工账号，再安排岗位" /> }} /></TableCard>
    <Modal title="新增人员账号" open={open} onCancel={() => setOpen(false)} onOk={() => void create()}
      confirmLoading={saving} okText="创建账号" cancelText="取消" width={480} forceRender>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="姓名" rules={[{ required: true, whitespace: true, message: '请输入姓名' }]}>
          <Input maxLength={50} placeholder="教职工姓名" />
        </Form.Item>
        <Form.Item name="phone" label="登录手机号" rules={[{ required: true, whitespace: true, message: '请输入手机号' }]}>
          <Input maxLength={20} placeholder="作为登录账号" />
        </Form.Item>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6, message: '密码至少6位' }]}>
          <Input.Password maxLength={64} placeholder="首次登录后可修改" />
        </Form.Item>
      </Form>
    </Modal>
    <Modal
      title={freezeTarget ? `冻结账号：${freezeTarget.name}` : '冻结账号'}
      open={!!freezeTarget}
      onCancel={() => { setFreezeTarget(null); freezeForm.resetFields() }}
      onOk={() => void confirmFreeze()}
      confirmLoading={saving}
      okText="确认冻结"
      cancelText="取消"
      width={460}
      forceRender
    >
      <p style={{ color: 'rgba(0,0,0,.6)', marginTop: 0 }}>冻结后该账号将无法登录，已有会话也会立即失效。请填写冻结原因：</p>
      <Form form={freezeForm} layout="vertical">
        <Form.Item name="reason" label="冻结原因" rules={[{ required: true, whitespace: true, message: '请填写冻结原因' }]}>
          <Input.TextArea maxLength={200} rows={3} showCount placeholder="例如：违规操作、离职交接中等" />
        </Form.Item>
      </Form>
    </Modal>
  </div>
}
