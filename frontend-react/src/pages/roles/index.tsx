import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, Modal, Popconfirm, Space, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { useNavigate } from 'react-router-dom'
import { rbacApi } from '@/api'
import EmptyState from '@/components/EmptyState'
import type { RoleInfo, RoleMember } from '@/types'

interface RoleFormValues {
  name: string
  code?: string
  description?: string
}

/** 根据角色code给出1~2个大字的头像缩写 + 颜色class */
function roleVisual(code: string): { initials: string; cls: string } {
  switch (code) {
    case 'school_admin':       return { initials: '校', cls: 'r_school_admin' }
    case 'academic_director':  return { initials: '教', cls: 'r_academic_director' }
    case 'head_teacher':       return { initials: '班', cls: 'r_head_teacher' }
    case 'subject_teacher':    return { initials: '任', cls: 'r_subject_teacher' }
    default: {
      const letters = (code || 'role').replace(/[^A-Za-z0-9\u4e00-\u9fa5]/g, '')
      return { initials: letters.slice(0, 2).toUpperCase() || 'R', cls: 'r_default' }
    }
  }
}

export default function RolesView() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<RoleInfo>()
  const [formOpen, setFormOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [memberRole, setMemberRole] = useState<RoleInfo>()
  const [members, setMembers] = useState<RoleMember[]>([])
  const [memberIds, setMemberIds] = useState<number[]>([])
  const [memberLoading, setMemberLoading] = useState(false)
  const [memberSaving, setMemberSaving] = useState(false)
  const [form] = Form.useForm<RoleFormValues>()

  const filteredRoles = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    if (!query) return roles
    return roles.filter((role) =>
      role.name.toLowerCase().includes(query) || role.code.toLowerCase().includes(query),
    )
  }, [keyword, roles])

  const load = async () => {
    setLoading(true)
    try {
      setRoles(await rbacApi.roles())
    } catch (error) {
      message.error(error instanceof Error ? error.message : '角色列表加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  const open = (role?: RoleInfo) => {
    setEditing(role)
    setFormOpen(true)
    form.setFieldsValue({
      name: role?.name ?? '',
      code: role?.code ?? '',
      description: role?.description ?? '',
    })
  }

  const save = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSaving(true)
    try {
      if (editing) {
        await rbacApi.updateRole(editing.id, { name: values.name.trim(), description: values.description?.trim() })
        message.success('角色已更新')
      } else {
        await rbacApi.createRole({ code: (values.code ?? '').trim(), name: values.name.trim(), description: values.description?.trim() })
        message.success('角色已创建')
      }
      setEditing(undefined)
      setFormOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存角色失败')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (role: RoleInfo) => {
    try {
      await rbacApi.deleteRole(role.id)
      message.success('角色已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除角色失败')
    }
  }

  const openMembers = async (role: RoleInfo) => {
    setMemberRole(role)
    setMemberLoading(true)
    try {
      const result = await rbacApi.roleMembers(role.id)
      setMembers(result.members)
      setMemberIds(result.members.filter((item) => item.assigned).map((item) => item.id))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '角色成员加载失败')
      setMemberRole(undefined)
    } finally {
      setMemberLoading(false)
    }
  }

  const saveMembers = async () => {
    if (!memberRole) return
    setMemberSaving(true)
    try {
      await rbacApi.setRoleMembers(memberRole.id, memberIds)
      message.success('角色成员已更新')
      setMemberRole(undefined)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '角色成员保存失败')
    } finally {
      setMemberSaving(false)
    }
  }

  const columns: TableProps<RoleInfo>['columns'] = [
    {
      title: '角色',
      key: 'name',
      width: 360,
      render: (_, item) => {
        const v = roleVisual(item.code)
        return (
          <div className="zh-role-identity">
            <div className={`zh-role-avatar ${v.cls}`}>{v.initials}</div>
            <div className="zh-role-meta">
              <div className="zh-role-meta-head">
                <span className="zh-role-name">{item.name}</span>
                {item.builtin && <span className="zh-role-tag-builtin">内置</span>}
              </div>
              <span className="zh-role-code">{item.code}</span>
              <span className="zh-role-desc">{item.description || <span style={{ color: 'var(--text-3)' }}>— 暂无说明</span>}</span>
            </div>
          </div>
        )
      },
    },
    {
      title: '权限点',
      dataIndex: 'permission_count',
      key: 'permission_count',
      width: 150,
      render: (count: number, item) => (
        <div className="zh-stat-cell">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="zh-stat-num">{count}</span>
            <span className="zh-stat-unit">项</span>
          </div>
          <Button type="link" className="zh-stat-action" onClick={() => navigate(`/permissions?role=${item.id}`)}>
            前往配置 →
          </Button>
        </div>
      ),
    },
    {
      title: '成员',
      dataIndex: 'member_count',
      key: 'member_count',
      width: 150,
      render: (count: number, item) => (
        <div className="zh-stat-cell">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
            <span className="zh-stat-num">{count}</span>
            <span className="zh-stat-unit">人</span>
          </div>
          <Button type="link" className="zh-stat-action" onClick={() => void openMembers(item)}>
            {item.code === 'school_admin' ? '查看成员' : '分配人员'} →
          </Button>
        </div>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 320,
      align: 'right',
      render: (_, item) => (
        <span className="zh-role-actions">
          <Button className="zh-role-pill-btn primary" onClick={() => navigate(`/permissions?role=${item.id}`)}>配置权限</Button>
          <Button className="zh-role-pill-btn" onClick={() => void openMembers(item)}>
            {item.code === 'school_admin' ? '查看成员' : '分配人员'}
          </Button>
          {!item.builtin && <Button className="zh-role-pill-btn" onClick={() => open(item)}>编辑</Button>}
          {!item.builtin && (
            <Popconfirm
              title="确定删除该角色？"
              description="删除后不可恢复，请确认该角色已不再使用。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => void remove(item)}
            >
              <Button className="zh-role-pill-btn danger">删除</Button>
            </Popconfirm>
          )}
        </span>
      ),
    },
  ]

  return (
    <div className="zh-page zh-role-page">
      {/* ===== Hero Header ===== */}
      <section className="zh-role-hero" aria-label="角色管理标题区">
        <div className="zh-role-hero-inner">
          <div>
            <h1>角色管理</h1>
            <p>
              角色决定一类人员可使用的功能权限。先创建角色，再到「权限管理」中为角色勾选权限点；
              内置角色由系统保留，不可删除。
            </p>
          </div>
          <Button type="primary" size="large" style={{
            borderRadius: 12,
            padding: '0 22px',
            height: 42,
            fontWeight: 700,
            background: 'linear-gradient(135deg, #3347A6, #5B4BE7)',
            border: 'none',
            boxShadow: '0 8px 20px -8px rgba(90,75,231,.55)',
          }} onClick={() => open()}>
            ＋ 新建角色
          </Button>
        </div>
      </section>

      {/* ===== Toolbar ===== */}
      <div className="zh-inline-toolbar">
        <Input.Search
          allowClear
          enterButton
          size="large"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索角色名称或编码，例如：教导主任 / academic_director"
          className="zh-role-search"
        />
        <div className="zh-role-count">
          共 <b>{filteredRoles.length}</b> 个角色
        </div>
      </div>

      {/* ===== Table ===== */}
      <Table<RoleInfo>
        rowKey="id"
        className="zh-role-table"
        rowClassName={() => 'zh-role-row'}
        columns={columns}
        dataSource={filteredRoles}
        loading={loading}
        pagination={filteredRoles.length > 10 ? { pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 项` } : false}
        locale={{ emptyText: (
          <EmptyState height={240} title="还没有任何角色" desc="点击右上角「新建角色」开始搭建你的岗位权限体系。" />
        )}}
      />

      {/* ===== Modal: 新建/编辑角色 ===== */}
      <Modal
        title={editing ? `编辑角色 · ${editing.name}` : '新建角色'}
        open={formOpen}
        onCancel={() => setFormOpen(false)}
        onOk={() => void save()}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={560}
        forceRender
        centered
        styles={{ body: { padding: '20px 24px 8px' } }}
      >
        <Form form={form} layout="vertical">
          <div className="zh-form-grid">
            <Form.Item name="name" label="角色名称" rules={[{ required: true, whitespace: true, message: '请输入角色名称' }]}>
              <Input placeholder="如：教导处干事" maxLength={50} />
            </Form.Item>
            <Form.Item name="code" label="角色编码" rules={[{ required: true, whitespace: true, message: '请输入角色编码' }]}>
              <Input placeholder="如：teaching_assistant（建议英文+下划线）" maxLength={50} disabled={!!editing} />
            </Form.Item>
          </div>
          <Form.Item name="description" label="角色说明">
            <Input.TextArea placeholder="描述该角色的职责范围，方便后续分配人员时参考" rows={3} maxLength={255} showCount />
          </Form.Item>
        </Form>
      </Modal>

      {/* ===== Modal: 分配/查看成员 ===== */}
      <Modal
        title={memberRole ? `${memberRole.code === 'school_admin' ? '查看' : '分配'}人员 · ${memberRole.name}` : '角色成员'}
        open={!!memberRole}
        onCancel={() => setMemberRole(undefined)}
        onOk={memberRole?.code === 'school_admin' ? () => setMemberRole(undefined) : () => void saveMembers()}
        confirmLoading={memberSaving}
        okText={memberRole?.code === 'school_admin' ? '关闭' : '保存分配'}
        cancelButtonProps={{ style: memberRole?.code === 'school_admin' ? { display: 'none' } : undefined }}
        width={820}
        centered
        destroyOnHidden
      >
        <Space className="zh-role-member-summary" wrap>
          {memberRole && <Tag color="blue">{memberRole.code}</Tag>}
          <span>已选择 <strong>{memberIds.length}</strong> 人</span>
          {memberRole?.code === 'school_admin' && (
            <Tag color="default" style={{ marginLeft: 8 }}>校长管理员由校长账号自动拥有</Tag>
          )}
        </Space>
        <Table<RoleMember>
          rowKey="id"
          size="middle"
          loading={memberLoading}
          dataSource={members}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          rowSelection={memberRole?.code === 'school_admin' ? undefined : {
            selectedRowKeys: memberIds,
            preserveSelectedRowKeys: true,
            onChange: (keys) => setMemberIds(keys as number[]),
            getCheckboxProps: (record) => ({ disabled: !record.assignable }),
          }}
          columns={[
            { title: '姓名', dataIndex: 'name', key: 'name', render: (name: string) => <strong style={{ fontSize: 14 }}>{name}</strong> },
            { title: '登录账号', dataIndex: 'phone', key: 'phone', width: 200 },
            {
              title: '账号状态',
              dataIndex: 'status',
              key: 'status',
              width: 120,
              render: (status: RoleMember['status']) => (
                <Tag color={status === 'active' ? 'success' : 'default'}>
                  {status === 'active' ? '正常' : '已停用'}
                </Tag>
              ),
            },
          ]}
        />
      </Modal>
    </div>
  )
}
