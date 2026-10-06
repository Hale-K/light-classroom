import { useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import { rbacApi } from '@/api'
import EmptyState from '@/components/EmptyState'
import PageHeader from '@/components/PageHeader'
import type {
  MenuNode,
  MenuPermissionBinding,
  PermissionGroup,
  RoleInfo,
  RoleMember,
  RoleMenuPreview,
} from '@/types'

interface RoleFormValues {
  name: string
  code?: string
  description?: string
}

function roleVisual(code: string): { initials: string; cls: string } {
  switch (code) {
    case 'school_admin':
      return { initials: '校', cls: 'r_school_admin' }
    case 'academic_director':
      return { initials: '教', cls: 'r_academic_director' }
    case 'head_teacher':
      return { initials: '班', cls: 'r_head_teacher' }
    case 'subject_teacher':
      return { initials: '任', cls: 'r_subject_teacher' }
    default: {
      const letters = (code || 'role').replace(/[^A-Za-z0-9\u4e00-\u9fa5]/g, '')
      return { initials: letters.slice(0, 2).toUpperCase() || 'R', cls: 'r_default' }
    }
  }
}

function sameCodes(a: string[], b: string[]) {
  if (a.length !== b.length) return false
  const saved = new Set(b)
  return a.every((code) => saved.has(code))
}

const RETIRED_PERMISSION_PREFIXES = ['scan:', 'paper:', 'grading:']

function isRetiredPermission(code: string) {
  return RETIRED_PERMISSION_PREFIXES.some((prefix) => code.startsWith(prefix))
}

export default function RbacWorkbenchView() {
  const { message, modal } = App.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [groups, setGroups] = useState<PermissionGroup[]>([])
  const [roleId, setRoleId] = useState<number>()
  const [roleKeyword, setRoleKeyword] = useState('')
  const [permKeyword, setPermKeyword] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [savedSelected, setSavedSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [savingPerms, setSavingPerms] = useState(false)
  const [activeTab, setActiveTab] = useState('permissions')

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<RoleInfo>()
  const [savingRole, setSavingRole] = useState(false)
  const [form] = Form.useForm<RoleFormValues>()

  const [members, setMembers] = useState<RoleMember[]>([])
  const [memberIds, setMemberIds] = useState<number[]>([])
  const [savedMemberIds, setSavedMemberIds] = useState<number[]>([])
  const [membersEditable, setMembersEditable] = useState(true)
  const [memberLoading, setMemberLoading] = useState(false)
  const [memberSaving, setMemberSaving] = useState(false)

  const [preview, setPreview] = useState<RoleMenuPreview>()
  const [previewLoading, setPreviewLoading] = useState(false)

  const [menuBindings, setMenuBindings] = useState<MenuPermissionBinding[]>([])
  const [menuDraft, setMenuDraft] = useState<Record<string, string[]>>({})
  const [menuLoading, setMenuLoading] = useState(false)
  const [menuSavingKey, setMenuSavingKey] = useState<string>()

  const currentRole = roles.find((role) => role.id === roleId)
  const allCodes = useMemo(
    () => groups.flatMap((group) => group.permissions.map((item) => item.code)),
    [groups],
  )
  const permissionOptions = useMemo(
    () =>
      groups.flatMap((group) =>
        group.permissions.map((item) => ({
          value: item.code,
          label: `${item.name}（${item.code}）`,
          group: group.module,
        })),
      ),
    [groups],
  )
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const permDirty = useMemo(
    () => !sameCodes(selected, savedSelected),
    [savedSelected, selected],
  )
  const memberDirty = useMemo(() => {
    const a = [...memberIds].sort((x, y) => x - y)
    const b = [...savedMemberIds].sort((x, y) => x - y)
    return a.length !== b.length || a.some((id, i) => id !== b[i])
  }, [memberIds, savedMemberIds])

  const filteredRoles = useMemo(() => {
    const query = roleKeyword.trim().toLowerCase()
    if (!query) return roles
    return roles.filter(
      (role) =>
        role.name.toLowerCase().includes(query) ||
        role.code.toLowerCase().includes(query),
    )
  }, [roleKeyword, roles])

  const filteredGroups = useMemo(() => {
    const query = permKeyword.trim().toLowerCase()
    if (!query) return groups
    return groups
      .map((group) => ({
        ...group,
        permissions: group.permissions.filter(
          (item) =>
            group.module.toLowerCase().includes(query) ||
            item.name.toLowerCase().includes(query) ||
            item.code.toLowerCase().includes(query),
        ),
      }))
      .filter((group) => group.permissions.length > 0)
  }, [groups, permKeyword])

  const loadRolesAndCatalog = async (preferRoleId?: number) => {
    setLoading(true)
    try {
      const [perms, roleList] = await Promise.all([
        rbacApi.permissions(),
        rbacApi.roles(),
      ])
      // Hide legacy catalog rows even when this frontend is connected to a
      // database that has not run the feature-removal migration yet.
      setGroups(
        perms
          .map((group) => ({
            ...group,
            permissions: group.permissions.filter((item) => !isRetiredPermission(item.code)),
          }))
          .filter((group) => group.permissions.length > 0),
      )
      setRoles(roleList)
      const fromUrl = Number(searchParams.get('role'))
      const candidates = [preferRoleId, fromUrl, roleId].filter(
        (id): id is number => typeof id === 'number' && id > 0,
      )
      const next =
        candidates.find((id) => roleList.some((role) => role.id === id)) ??
        roleList[0]?.id
      if (next !== undefined) {
        setRoleId(next)
        setSearchParams({ role: String(next) }, { replace: true })
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '角色与权限加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadRolesAndCatalog()
    // 仅首屏加载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (roleId === undefined) {
      setSelected([])
      setSavedSelected([])
      setMembers([])
      setMemberIds([])
      setSavedMemberIds([])
      setPreview(undefined)
      return
    }
    let cancelled = false
    setPermissionLoading(true)
    setMemberLoading(true)
    Promise.all([
      rbacApi.rolePermissions(roleId),
      rbacApi.roleMembers(roleId),
    ])
      .then(([codes, memberResult]) => {
        if (cancelled) return
        const activeCodes = codes.filter((code) => !isRetiredPermission(code))
        setSelected(activeCodes)
        setSavedSelected(activeCodes)
        setMembers(memberResult.members)
        setMembersEditable(memberResult.editable)
        const assigned = memberResult.members
          .filter((item) => item.assigned)
          .map((item) => item.id)
        setMemberIds(assigned)
        setSavedMemberIds(assigned)
      })
      .catch((error) => {
        if (!cancelled) {
          message.error(error instanceof Error ? error.message : '角色详情加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setPermissionLoading(false)
          setMemberLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [roleId])

  useEffect(() => {
    if (roleId === undefined || activeTab !== 'menu') return
    let cancelled = false
    const timer = window.setTimeout(() => {
      setPreviewLoading(true)
      rbacApi
        .roleMenuPreview(roleId, selected)
        .then((data) => {
          if (!cancelled) setPreview(data)
        })
        .catch((error) => {
          if (!cancelled) {
            message.error(error instanceof Error ? error.message : '菜单预览失败')
          }
        })
        .finally(() => {
          if (!cancelled) setPreviewLoading(false)
        })
    }, 280)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [activeTab, roleId, selected])

  useEffect(() => {
    if (activeTab !== 'menu-config') return
    let cancelled = false
    setMenuLoading(true)
    rbacApi
      .menuPermissions()
      .then((rows) => {
        if (cancelled) return
        setMenuBindings(rows)
        setMenuDraft(
          Object.fromEntries(rows.map((row) => [row.key, [...row.permission_codes]])),
        )
      })
      .catch((error) => {
        if (!cancelled) {
          message.error(error instanceof Error ? error.message : '菜单权限映射加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) setMenuLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeTab])

  const selectRole = (id: number) => {
    if (id === roleId) return
    const apply = () => {
      setRoleId(id)
      setPermKeyword('')
      setActiveTab('permissions')
      setSearchParams({ role: String(id) }, { replace: true })
    }
    if (!permDirty && !memberDirty) {
      apply()
      return
    }
    modal.confirm({
      title: '放弃尚未保存的修改？',
      content: '切换角色后，当前权限或成员勾选变化将不会保留。',
      okText: '放弃并切换',
      cancelText: '继续编辑',
      onOk: apply,
    })
  }

  const openRoleForm = (role?: RoleInfo) => {
    setEditing(role)
    setFormOpen(true)
    form.setFieldsValue({
      name: role?.name ?? '',
      code: role?.code ?? '',
      description: role?.description ?? '',
    })
  }

  const saveRole = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    setSavingRole(true)
    try {
      if (editing) {
        await rbacApi.updateRole(editing.id, {
          name: values.name.trim(),
          description: values.description?.trim(),
        })
        message.success('角色已更新')
        await loadRolesAndCatalog(editing.id)
      } else {
        const created = await rbacApi.createRole({
          code: (values.code ?? '').trim(),
          name: values.name.trim(),
          description: values.description?.trim(),
        })
        message.success('角色已创建')
        await loadRolesAndCatalog(created.id)
      }
      setFormOpen(false)
      setEditing(undefined)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存角色失败')
    } finally {
      setSavingRole(false)
    }
  }

  const removeRole = async (role: RoleInfo) => {
    try {
      await rbacApi.deleteRole(role.id)
      message.success('角色已删除')
      const nextPrefer = roleId === role.id ? undefined : roleId
      await loadRolesAndCatalog(nextPrefer)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除角色失败')
    }
  }

  const toggleModule = (group: PermissionGroup, checked: boolean) => {
    const codes = group.permissions.map((item) => item.code)
    const next = new Set(selected)
    codes.forEach((code) => (checked ? next.add(code) : next.delete(code)))
    setSelected(Array.from(next))
  }

  /** 每个模块各自一个 Checkbox.Group，变更时只合并该组，避免冲掉其它模块已选 */
  const replaceGroupSelection = (groupCodes: string[], nextInGroup: string[]) => {
    const groupSet = new Set(groupCodes)
    const kept = selected.filter((code) => !groupSet.has(code))
    setSelected([...kept, ...nextInGroup])
  }

  const savePermissions = async () => {
    if (roleId === undefined) return
    setSavingPerms(true)
    try {
      await rbacApi.setRolePermissions(roleId, selected)
      message.success('权限已保存')
      setSavedSelected(selected)
      setRoles((prev) =>
        prev.map((role) =>
          role.id === roleId
            ? { ...role, permission_count: selected.length }
            : role,
        ),
      )
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存权限失败')
    } finally {
      setSavingPerms(false)
    }
  }

  const saveMembers = async () => {
    if (roleId === undefined || !membersEditable) return
    setMemberSaving(true)
    try {
      await rbacApi.setRoleMembers(roleId, memberIds)
      message.success('角色成员已更新')
      setSavedMemberIds(memberIds)
      setRoles((prev) =>
        prev.map((role) =>
          role.id === roleId
            ? { ...role, member_count: memberIds.length }
            : role,
        ),
      )
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存成员失败')
    } finally {
      setMemberSaving(false)
    }
  }

  const saveMenuBinding = async (menuKey: string) => {
    const codes = menuDraft[menuKey] || []
    setMenuSavingKey(menuKey)
    try {
      const result = await rbacApi.setMenuPermissions(menuKey, codes)
      message.success('菜单权限已保存')
      setMenuBindings((prev) =>
        prev.map((row) =>
          row.key === menuKey
            ? {
                ...row,
                permission_codes: result.permissions,
                configured: result.permissions.length > 0,
              }
            : row,
        ),
      )
      setMenuDraft((prev) => ({ ...prev, [menuKey]: [...result.permissions] }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存菜单权限失败')
    } finally {
      setMenuSavingKey(undefined)
    }
  }

  const renderMenuTree = (nodes: MenuNode[]) => (
    <ul className="zh-rbac-menu-tree">
      {nodes.map((node) => (
        <li key={node.key}>
          <div className="zh-rbac-menu-node">
            <strong>{node.title}</strong>
            {node.path && <code>{node.path}</code>}
          </div>
          {node.children && node.children.length > 0 && renderMenuTree(node.children)}
        </li>
      ))}
    </ul>
  )

  return (
    <div className="zh-page zh-rbac-page">
      <PageHeader title="角色与权限" />
      <p className="zh-page-desc">
        角色 = 一组权限 + 一批人。改权限会影响该角色所有成员的菜单与功能；
        「菜单预览」按当前勾选模拟侧栏；「菜单配置」维护侧栏菜单与权限点的数据库映射。
      </p>

      <div className="zh-rbac-workbench">
        <aside className="zh-rbac-roles" aria-label="角色列表">
          <div className="zh-rbac-roles-head">
            <Input.Search
              allowClear
              value={roleKeyword}
              onChange={(event) => setRoleKeyword(event.target.value)}
              placeholder="搜索角色"
              size="middle"
            />
            <Button type="primary" onClick={() => openRoleForm()}>
              新建
            </Button>
          </div>
          <div className="zh-rbac-role-list" aria-busy={loading}>
            {filteredRoles.map((role) => {
              const visual = roleVisual(role.code)
              const active = role.id === roleId
              return (
                <button
                  key={role.id}
                  type="button"
                  className={`zh-rbac-role-card${active ? ' is-active' : ''}`}
                  onClick={() => selectRole(role.id)}
                >
                  <div className={`zh-role-avatar ${visual.cls}`}>{visual.initials}</div>
                  <div className="zh-rbac-role-meta">
                    <div className="zh-role-meta-head">
                      <span className="zh-role-name">{role.name}</span>
                      {role.builtin && <span className="zh-role-tag-builtin">内置</span>}
                    </div>
                    <span className="zh-role-code">{role.code}</span>
                    <span className="zh-rbac-role-stats">
                      {role.permission_count} 项权限 · {role.member_count} 人
                    </span>
                  </div>
                </button>
              )
            })}
            {!loading && filteredRoles.length === 0 && (
              <EmptyState height={160} title="没有匹配角色" desc="试试调整搜索词，或新建一个角色" />
            )}
          </div>
        </aside>

        <section className="zh-rbac-detail">
          {!currentRole ? (
            <EmptyState height={320} title="暂无角色" desc="请先在左侧新建角色" />
          ) : (
            <>
              <div className="zh-rbac-detail-head">
                <div>
                  <h2>
                    {currentRole.name}
                    {currentRole.builtin && (
                      <Tag style={{ marginLeft: 8 }}>内置</Tag>
                    )}
                  </h2>
                  <p>{currentRole.description || '暂无说明'}</p>
                </div>
                <Space wrap>
                  {!currentRole.builtin && (
                    <Button onClick={() => openRoleForm(currentRole)}>编辑角色</Button>
                  )}
                  {!currentRole.builtin && (
                    <Popconfirm
                      title="确定删除该角色？"
                      description="删除后不可恢复，请确认该角色已不再使用。"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={() => void removeRole(currentRole)}
                    >
                      <Button danger>删除</Button>
                    </Popconfirm>
                  )}
                  {permDirty && <Tag color="warning">权限未保存</Tag>}
                  {memberDirty && <Tag color="warning">成员未保存</Tag>}
                </Space>
              </div>

              <Tabs
                activeKey={activeTab}
                onChange={setActiveTab}
                items={[
                  {
                    key: 'permissions',
                    label: `权限点（${selected.length}/${allCodes.length}）`,
                    children: (
                      <div className="zh-rbac-tab-body">
                        <div className="zh-inline-toolbar">
                          <Input.Search
                            allowClear
                            value={permKeyword}
                            onChange={(event) => setPermKeyword(event.target.value)}
                            placeholder="搜索权限模块、名称或编码"
                            className="zh-role-search"
                          />
                          <Space wrap>
                            <Button
                              disabled={permissionLoading}
                              onClick={() => setSelected(allCodes)}
                            >
                              全部勾选
                            </Button>
                            <Button
                              disabled={permissionLoading || selected.length === 0}
                              onClick={() => setSelected([])}
                            >
                              全部清空
                            </Button>
                            <Button
                              type="primary"
                              disabled={!permDirty || permissionLoading}
                              loading={savingPerms}
                              onClick={() => void savePermissions()}
                            >
                              保存权限
                            </Button>
                          </Space>
                        </div>
                        <div className="zh-permission-stack" aria-busy={permissionLoading}>
                          {filteredGroups.map((group) => {
                            const codes = group.permissions.map((item) => item.code)
                            const checkedCount = codes.filter((code) =>
                              selectedSet.has(code),
                            ).length
                            const allChecked = checkedCount === codes.length && codes.length > 0
                            return (
                              <div key={group.module} className="zh-perm-module">
                                <div className="zh-perm-module-head">
                                  <strong>{group.module}</strong>
                                  <Checkbox
                                    checked={allChecked}
                                    indeterminate={checkedCount > 0 && !allChecked}
                                    onChange={(e) =>
                                      toggleModule(group, e.target.checked)
                                    }
                                  >
                                    {checkedCount > 0
                                      ? `已选 ${checkedCount} / ${codes.length}`
                                      : '全选'}
                                  </Checkbox>
                                </div>
                                <Checkbox.Group
                                  value={codes.filter((code) => selectedSet.has(code))}
                                  onChange={(values) =>
                                    replaceGroupSelection(codes, values as string[])
                                  }
                                >
                                  <div className="zh-perm-item-list">
                                    {group.permissions.map((item) => (
                                      <label key={item.code} className="zh-perm-item">
                                        <Checkbox value={item.code}>{item.name}</Checkbox>
                                        <code>{item.code}</code>
                                      </label>
                                    ))}
                                  </div>
                                </Checkbox.Group>
                              </div>
                            )
                          })}
                          {!permissionLoading && filteredGroups.length === 0 && (
                            <EmptyState
                              height={180}
                              title="没有匹配的权限点"
                              desc="请调整搜索关键词"
                            />
                          )}
                        </div>
                      </div>
                    ),
                  },
                  {
                    key: 'members',
                    label: `成员（${memberIds.length}）`,
                    children: (
                      <div className="zh-rbac-tab-body">
                        <div className="zh-inline-toolbar">
                          <Space wrap>
                            <Tag color="blue">{currentRole.code}</Tag>
                            <span>
                              已选择 <strong>{memberIds.length}</strong> 人
                            </span>
                            {!membersEditable && (
                              <Tag>校长管理员由校长账号自动拥有，不可手工分配</Tag>
                            )}
                          </Space>
                          {membersEditable && (
                            <Button
                              type="primary"
                              disabled={!memberDirty || memberLoading}
                              loading={memberSaving}
                              onClick={() => void saveMembers()}
                            >
                              保存成员
                            </Button>
                          )}
                        </div>
                        <Table<RoleMember>
                          rowKey="id"
                          size="middle"
                          loading={memberLoading}
                          dataSource={members}
                          pagination={{ pageSize: 10, showSizeChanger: false }}
                          rowSelection={
                            membersEditable
                              ? {
                                  selectedRowKeys: memberIds,
                                  preserveSelectedRowKeys: true,
                                  onChange: (keys) => setMemberIds(keys as number[]),
                                  getCheckboxProps: (record) => ({
                                    disabled: !record.assignable,
                                  }),
                                }
                              : undefined
                          }
                          columns={[
                            {
                              title: '姓名',
                              dataIndex: 'name',
                              key: 'name',
                              render: (name: string) => <strong>{name}</strong>,
                            },
                            {
                              title: '登录账号',
                              dataIndex: 'phone',
                              key: 'phone',
                              width: 200,
                            },
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
                      </div>
                    ),
                  },
                  {
                    key: 'menu',
                    label: '菜单预览',
                    children: (
                      <div className="zh-rbac-tab-body">
                        <p className="zh-rbac-preview-hint">
                          按当前权限勾选模拟该角色登录后的侧栏（含未保存草稿）。
                          与真实登录菜单一致处取决于权限码映射；保存后成员重新进入系统即可生效。
                          {permDirty && (
                            <Tag color="warning" style={{ marginLeft: 8 }}>
                              预览含未保存修改
                            </Tag>
                          )}
                        </p>
                        {previewLoading && !preview ? (
                          <EmptyState height={200} title="正在生成预览…" desc="" />
                        ) : preview && preview.menus.length > 0 ? (
                          <div className="zh-rbac-menu-preview" aria-busy={previewLoading}>
                            {renderMenuTree(preview.menus)}
                          </div>
                        ) : (
                          <EmptyState
                            height={200}
                            title="当前勾选下无可见菜单"
                            desc="请至少勾选带 view 的权限点，例如「查看工作台」"
                          />
                        )}
                      </div>
                    ),
                  },
                  {
                    key: 'menu-config',
                    label: '菜单配置',
                    children: (
                      <div className="zh-rbac-tab-body">
                        <p className="zh-rbac-preview-hint">
                          配置每个侧栏菜单需要哪些权限点才可见（满足<strong>任一</strong>即可）。
                          清空并保存后，该菜单回退到基础角色白名单。映射保存在数据库，改完立即影响非校长用户的侧栏。
                        </p>
                        <Table<MenuPermissionBinding>
                          rowKey="key"
                          size="middle"
                          loading={menuLoading}
                          dataSource={menuBindings}
                          pagination={false}
                          columns={[
                            {
                              title: '菜单',
                              key: 'menu',
                              width: 200,
                              render: (_, row) => (
                                <div>
                                  <strong>{row.title}</strong>
                                  <div>
                                    <code style={{ fontSize: 11, color: 'var(--text-3)' }}>
                                      {row.path}
                                    </code>
                                  </div>
                                </div>
                              ),
                            },
                            {
                              title: '分组',
                              dataIndex: 'group',
                              key: 'group',
                              width: 110,
                            },
                            {
                              title: '可见权限点（任一）',
                              key: 'permissions',
                              render: (_, row) => {
                                const draft = menuDraft[row.key] || []
                                const dirty = !sameCodes(draft, row.permission_codes)
                                return (
                                  <div className="zh-rbac-menu-perm-row">
                                    <Select
                                      mode="multiple"
                                      allowClear
                                      showSearch
                                      optionFilterProp="label"
                                      style={{ width: '100%', minWidth: 260 }}
                                      placeholder="未配置则按角色白名单"
                                      value={draft}
                                      options={permissionOptions}
                                      onChange={(values: string[]) =>
                                        setMenuDraft((prev) => ({
                                          ...prev,
                                          [row.key]: values,
                                        }))
                                      }
                                    />
                                    <Button
                                      type="primary"
                                      size="small"
                                      disabled={!dirty}
                                      loading={menuSavingKey === row.key}
                                      onClick={() => void saveMenuBinding(row.key)}
                                    >
                                      保存
                                    </Button>
                                  </div>
                                )
                              },
                            },
                            {
                              title: '状态',
                              key: 'status',
                              width: 110,
                              render: (_, row) => {
                                const draft = menuDraft[row.key] || []
                                if (draft.length === 0) {
                                  return <Tag>角色白名单</Tag>
                                }
                                return (
                                  <Tag color="blue">{draft.length} 个权限</Tag>
                                )
                              },
                            },
                          ]}
                        />
                      </div>
                    ),
                  },
                ]}
              />
            </>
          )}
        </section>
      </div>

      <Modal
        title={editing ? `编辑角色 · ${editing.name}` : '新建角色'}
        open={formOpen}
        onCancel={() => setFormOpen(false)}
        onOk={() => void saveRole()}
        confirmLoading={savingRole}
        okText="保存"
        cancelText="取消"
        width={560}
        forceRender
        centered
      >
        <Form form={form} layout="vertical">
          <div className="zh-form-grid">
            <Form.Item
              name="name"
              label="角色名称"
              rules={[{ required: true, whitespace: true, message: '请输入角色名称' }]}
            >
              <Input placeholder="如：教导处干事" maxLength={50} />
            </Form.Item>
            <Form.Item
              name="code"
              label="角色编码"
              rules={[{ required: true, whitespace: true, message: '请输入角色编码' }]}
            >
              <Input
                placeholder="如：teaching_assistant"
                maxLength={50}
                disabled={!!editing}
              />
            </Form.Item>
          </div>
          <Form.Item name="description" label="角色说明">
            <Input.TextArea
              placeholder="描述该角色的职责范围"
              rows={3}
              maxLength={255}
              showCount
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
