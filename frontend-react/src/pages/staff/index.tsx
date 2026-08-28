import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Switch, Table } from 'antd'
import type { TableProps } from 'antd'
import { staffApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import { useAuthStore } from '@/store/auth'
import { STAFF_ROLE_DICT } from '@/types/dict'
import type { StaffAccount, StaffRoleCode, StaffRoleOption } from '@/types'
import {
  buildStaffOrgTree,
  filterStaffByOrgNode,
  type StaffOrgNodeKey,
} from './org-tree'

interface StaffFormValues {
  name?: string
  phone?: string
  password?: string
  roles: StaffRoleCode[]
}

export default function StaffView() {
  const { message } = App.useApp()
  const schoolCode = useAuthStore((state) => state.schoolCode)
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [roleOptions, setRoleOptions] = useState<StaffRoleOption[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dialogVisible, setDialogVisible] = useState(false)
  const [editing, setEditing] = useState<StaffAccount>()
  const [keyword, setKeyword] = useState('')
  const [roleFilter, setRoleFilter] = useState<StaffRoleCode | ''>('')
  const [statusFilter, setStatusFilter] = useState<'active' | 'disabled' | ''>('')
  const [selectedOrg, setSelectedOrg] = useState<StaffOrgNodeKey>('school')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [form] = Form.useForm<StaffFormValues>()

  const orgTree = useMemo(
    () => buildStaffOrgTree(accounts, schoolCode || '当前学校'),
    [accounts, schoolCode],
  )

  const selectedOrgNode =
    selectedOrg === 'school'
      ? orgTree
      : orgTree.children.find((node) => node.key === selectedOrg) ?? orgTree

  const filteredAccounts = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return filterStaffByOrgNode(accounts, selectedOrg).filter((item) => {
      const matchesKeyword =
        !query || item.name.toLowerCase().includes(query) || item.phone.includes(query)
      const matchesRole = !roleFilter || item.roles.includes(roleFilter)
      const matchesStatus = !statusFilter || item.status === statusFilter
      return matchesKeyword && matchesRole && matchesStatus
    })
  }, [accounts, keyword, roleFilter, selectedOrg, statusFilter])

  const pagedAccounts = useMemo(
    () => filteredAccounts.slice((page - 1) * pageSize, page * pageSize),
    [filteredAccounts, page, pageSize],
  )

  useEffect(() => {
    setPage(1)
  }, [keyword, roleFilter, selectedOrg, statusFilter])

  const resetFilters = () => {
    setKeyword('')
    setRoleFilter('')
    setStatusFilter('')
  }

  const loadStaff = async () => {
    setLoading(true)
    try {
      const data = await staffApi.list()
      setAccounts(data.accounts)
      setRoleOptions(data.roles)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadStaff()
  }, [])

  const openCreate = () => {
    setEditing(undefined)
    form.setFieldsValue({ name: '', phone: '', password: '', roles: ['subject_teacher'] })
    setDialogVisible(true)
  }

  const openRoles = (account: StaffAccount) => {
    setEditing(account)
    form.setFieldsValue({
      name: account.name,
      phone: account.phone,
      password: '',
      roles: account.roles.filter((role) => role !== 'school_admin') as StaffRoleCode[],
    })
    setDialogVisible(true)
  }

  const submit = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    if (!values.roles.length) {
      message.warning('请至少分配一个角色')
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await staffApi.updateRoles(editing.id, values.roles)
        message.success('角色分配已更新')
      } else {
        await staffApi.create({
          name: (values.name ?? '').trim(),
          phone: (values.phone ?? '').trim(),
          password: values.password ?? '',
          roles: values.roles,
        })
        message.success('教职工账号已创建')
      }
      setDialogVisible(false)
      await loadStaff()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleStatus = async (account: StaffAccount, active: boolean) => {
    const previous = account.status
    const next = active ? 'active' : 'disabled'
    setAccounts((prev) =>
      prev.map((item) => (item.id === account.id ? { ...item, status: next } : item)),
    )
    try {
      await staffApi.updateStatus(account.id, next)
      message.success(next === 'active' ? '账号已启用' : '账号已停用')
    } catch (error) {
      setAccounts((prev) =>
        prev.map((item) => (item.id === account.id ? { ...item, status: previous } : item)),
      )
      message.error(error instanceof Error ? error.message : '账号状态更新失败')
    }
  }

  const columns: TableProps<StaffAccount>['columns'] = [
    {
      title: '人员',
      key: 'person',
      width: 180,
      render: (_, record) => (
        <div className="zh-person-cell">
          <strong>{record.name}</strong>
          <span>{record.phone}</span>
        </div>
      ),
    },
    {
      title: '角色',
      key: 'roles',
      width: 340,
      render: (_, record) => (
        <div className="zh-role-tags">
          {record.roles.map((role) => (
            <DictTag key={role} dict={STAFF_ROLE_DICT} value={role} />
          ))}
        </div>
      ),
    },
    {
      title: '账号状态',
      key: 'status',
      width: 130,
      render: (_, record) => (
        <Switch
          checked={record.status === 'active'}
          disabled={record.is_school_admin}
          checkedChildren="启用"
          unCheckedChildren="停用"
          onChange={(checked) => toggleStatus(record, checked)}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      align: 'right',
      render: (_, record) =>
        record.is_school_admin ? (
          <span className="zh-locked">校长账号</span>
        ) : (
          <Button type="link" size="small" onClick={() => openRoles(record)}>
            分配角色
          </Button>
        ),
    },
  ]

  return (
    <div className="zh-page">
      <PageHeader
        title="人员与权限"
        extra={
          <Button type="primary" onClick={openCreate}>
            新增教职工
          </Button>
        }
      />
      <p className="zh-page-desc">
        校长管理本校登录账号；班主任、任教老师和教导主任可按实际职责组合分配。
      </p>

      <div className="zh-role-note">
        <strong>权限原则</strong>
        <span>校长管理员不可降权；教职工可同时承担多个角色，教导主任拥有排课、选科分班和排考管理权限。</span>
      </div>

      <div className="zh-staff-workspace">
        <aside className="zh-org-panel" aria-label="人员组织架构">
          <div className="zh-org-heading">
            <span>组织架构</span>
            <small>按人员职责归属</small>
          </div>
          <div className="zh-org-tree" role="tree" aria-label="学校人员组织树">
            <button
              type="button"
              role="treeitem"
              aria-selected={selectedOrg === 'school'}
              className={`zh-org-node zh-org-root${selectedOrg === 'school' ? ' active' : ''}`}
              onClick={() => setSelectedOrg('school')}
            >
              <span className="zh-org-icon"><Icon name="users" size={16} /></span>
              <span className="zh-org-copy">
                <strong>{orgTree.title}</strong>
                <small>{orgTree.description}</small>
              </span>
              <b>{orgTree.count}</b>
            </button>
            <div className="zh-org-branches" role="group">
              {orgTree.children.map((node) => (
                <button
                  key={node.key}
                  type="button"
                  role="treeitem"
                  aria-selected={selectedOrg === node.key}
                  className={`zh-org-node${selectedOrg === node.key ? ' active' : ''}`}
                  onClick={() => setSelectedOrg(node.key)}
                >
                  <span className="zh-org-branch-mark" aria-hidden="true" />
                  <span className="zh-org-copy">
                    <strong>{node.title}</strong>
                    <small>{node.description}</small>
                  </span>
                  <b>{node.count}</b>
                </button>
              ))}
            </div>
          </div>
          <p className="zh-org-tip">一人兼任多个职责时，会出现在对应的多个节点中。</p>
        </aside>

        <section className="zh-staff-directory" aria-labelledby="staff-directory-title">
          <div className="zh-staff-directory-head">
            <div>
              <h2 id="staff-directory-title">{selectedOrgNode.title}</h2>
              <span>{selectedOrgNode.description} · {selectedOrgNode.count} 人</span>
            </div>
          </div>
          <FilterCard>
            <div className="zh-filter-row">
              <label className="zh-filter-field">
                <span>人员</span>
                <Input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  allowClear
                  placeholder="姓名或手机号"
                  style={{ width: 220 }}
                />
              </label>
              <label className="zh-filter-field">
                <span>角色</span>
                <Select
                  value={roleFilter || undefined}
                  onChange={(v) => setRoleFilter((v ?? '') as StaffRoleCode | '')}
                  allowClear
                  placeholder="全部角色"
                  style={{ width: 170 }}
                  options={roleOptions.map((r) => ({ label: r.name, value: r.code }))}
                />
              </label>
              <label className="zh-filter-field">
                <span>状态</span>
                <Select
                  value={statusFilter || undefined}
                  onChange={(v) => setStatusFilter((v ?? '') as 'active' | 'disabled' | '')}
                  allowClear
                  placeholder="全部状态"
                  style={{ width: 130 }}
                  options={[
                    { label: '启用', value: 'active' },
                    { label: '停用', value: 'disabled' },
                  ]}
                />
              </label>
              <Button onClick={resetFilters}>重置</Button>
              <span className="zh-filter-count">筛选结果 {filteredAccounts.length} 人</span>
            </div>
          </FilterCard>

          <TableCard>
            <Table<StaffAccount>
          rowKey="id"
          columns={columns}
          dataSource={pagedAccounts}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: filteredAccounts.length,
            onChange: (p, s) => {
              setPage(p)
              setPageSize(s)
            },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
              locale={{
                emptyText: (
                  <EmptyState
                    height={220}
                    title={`“${selectedOrgNode.title}”暂无人员`}
                    desc="可调整筛选条件，或点击右上角新增教职工"
                  />
                ),
              }}
            />
          </TableCard>
        </section>
      </div>

      <Modal
        title={editing ? '分配人员角色' : '新增教职工账号'}
        open={dialogVisible}
        onCancel={() => setDialogVisible(false)}
        onOk={submit}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={520}
        forceRender
      >
        <Form form={form} layout="vertical" name="staffForm">
          {editing ? (
            <div className="zh-editing-person">
              <strong>{editing.name}</strong>
              <span>{editing.phone}</span>
            </div>
          ) : (
            <div className="zh-form-grid">
              <Form.Item
                name="name"
                label="姓名"
                rules={[{ required: true, whitespace: true, message: '请输入姓名' }]}
              >
                <Input placeholder="请输入姓名" maxLength={50} />
              </Form.Item>
              <Form.Item
                name="phone"
                label="登录手机号"
                rules={[{ required: true, whitespace: true, message: '请输入手机号' }]}
              >
                <Input placeholder="登录手机号" maxLength={20} />
              </Form.Item>
              <Form.Item
                name="password"
                label="初始密码"
                className="zh-form-wide"
                rules={[{ required: true, message: '请设置初始密码' }]}
              >
                <Input.Password placeholder="请设置初始密码" maxLength={64} />
              </Form.Item>
            </div>
          )}
          <Form.Item
            name="roles"
            label="人员角色"
            rules={[{ required: true, message: '请至少分配一个角色' }]}
          >
            <Select
              mode="multiple"
              placeholder="请选择角色"
              options={roleOptions.map((r) => ({ label: r.name, value: r.code }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
