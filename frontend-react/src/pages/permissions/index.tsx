import { useEffect, useMemo, useState } from 'react'
import { App, Button, Checkbox, Input, Select, Space, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'
import { rbacApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'
import type { PermissionGroup, RoleInfo } from '@/types'

export default function PermissionsView() {
  const { message, modal } = App.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [groups, setGroups] = useState<PermissionGroup[]>([])
  const [roleId, setRoleId] = useState<number>()
  const [selected, setSelected] = useState<string[]>([])
  const [savedSelected, setSavedSelected] = useState<string[]>([])
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const currentRole = roles.find((role) => role.id === roleId)
  const allCodes = useMemo(() => groups.flatMap((group) => group.permissions.map((item) => item.code)), [groups])
  const selectedSet = useMemo(() => new Set(selected), [selected])
  const dirty = useMemo(() => {
    const saved = new Set(savedSelected)
    return selected.length !== savedSelected.length || selected.some((code) => !saved.has(code))
  }, [savedSelected, selected])
  const filteredGroups = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    if (!query) return groups
    return groups.map((group) => ({
      ...group,
      permissions: group.permissions.filter((item) =>
        group.module.toLowerCase().includes(query)
        || item.name.toLowerCase().includes(query)
        || item.code.toLowerCase().includes(query),
      ),
    })).filter((group) => group.permissions.length > 0)
  }, [groups, keyword])

  // 初始加载：权限目录 + 角色列表，并尝试按 URL 中的 role 预选
  useEffect(() => {
    setLoading(true)
    Promise.all([rbacApi.permissions(), rbacApi.roles()])
      .then(([perms, roleList]) => {
        setGroups(perms)
        setRoles(roleList)
        const initial = Number(searchParams.get('role'))
        if (roleList.some((role) => role.id === initial)) setRoleId(initial)
      })
      .catch((error) => message.error(error instanceof Error ? error.message : '权限目录加载失败'))
      .finally(() => setLoading(false))
  }, [])

  // 切换角色时拉取其已勾选的权限
  useEffect(() => {
    if (roleId === undefined) { setSelected([]); setSavedSelected([]); return }
    let cancelled = false
    setPermissionLoading(true)
    rbacApi.rolePermissions(roleId)
      .then((codes) => { if (!cancelled) { setSelected(codes); setSavedSelected(codes) } })
      .catch((error) => { if (!cancelled) message.error(error instanceof Error ? error.message : '角色权限加载失败') })
      .finally(() => { if (!cancelled) setPermissionLoading(false) })
    return () => { cancelled = true }
  }, [roleId])

  const onSelectRole = (id: number) => {
    const apply = () => {
      setRoleId(id)
      setKeyword('')
      setSearchParams({ role: String(id) }, { replace: true })
    }
    if (!dirty) { apply(); return }
    modal.confirm({
      title: '放弃尚未保存的权限调整？',
      content: '切换角色后，当前勾选变化将不会保留。',
      okText: '放弃并切换',
      cancelText: '继续编辑',
      onOk: apply,
    })
  }

  const toggleModule = (group: PermissionGroup, checked: boolean) => {
    const codes = group.permissions.map((item) => item.code)
    const next = new Set(selected)
    codes.forEach((code) => (checked ? next.add(code) : next.delete(code)))
    setSelected(Array.from(next))
  }

  const save = async () => {
    if (roleId === undefined) return
    setSaving(true)
    try {
      await rbacApi.setRolePermissions(roleId, selected)
      message.success('权限已保存')
      setSavedSelected(selected)
      const updated = roles.find((role) => role.id === roleId)
      if (updated) updated.permission_count = selected.length
      setRoles([...roles])
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存权限失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="zh-page">
      <PageHeader title="权限管理" />
      <p className="zh-page-desc">按模块为角色勾选可使用的功能权限点。先选择一个角色，再调整其权限并保存；配置结果即时生效到该角色的所有人员。</p>

      <FilterCard>
        <div className="zh-filter-row">
          <label className="zh-filter-field" style={{ minWidth: 320 }}>
            <span>选择角色</span>
            <Select value={roleId} loading={loading} placeholder="请选择要配置权限的角色" style={{ width: 320 }} showSearch
              optionFilterProp="label" onChange={(id: number) => onSelectRole(id)}
              options={roles.map((role) => ({ value: role.id, label: role.name }))} />
          </label>
          {currentRole && <span className="zh-filter-count">已勾选 <strong>{selected.length}</strong> / {allCodes.length} 项权限点</span>}
        </div>
      </FilterCard>

      {currentRole && <div className="zh-inline-toolbar">
        <Input.Search allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索权限模块、名称或编码" className="zh-role-search" />
        <Space wrap>
          <Tag>{currentRole.member_count} 名成员</Tag>
          {dirty && <Tag color="warning">有未保存修改</Tag>}
        </Space>
      </div>}

      <TableCard
        title={currentRole ? `角色「${currentRole.name}」的权限` : '权限点目录'}
        extra={currentRole ? <Space>
          <Button disabled={permissionLoading} onClick={() => setSelected(allCodes)}>全部勾选</Button>
          <Button disabled={permissionLoading || selected.length === 0} onClick={() => setSelected([])}>全部清空</Button>
          <Button type="primary" disabled={!dirty || permissionLoading} loading={saving} onClick={() => void save()}>保存权限</Button>
        </Space> : undefined}
      >
        {roleId === undefined ? (
          <EmptyState height={240} title="请先选择角色" desc="选择上方角色后即可为它分配与调整权限点" />
        ) : (
          <div className="zh-permission-stack" aria-busy={permissionLoading}>
            {filteredGroups.map((group) => {
              const codes = group.permissions.map((item) => item.code)
              const checkedCount = codes.filter((code) => selectedSet.has(code)).length
              const allChecked = checkedCount === codes.length
              return (
                <div key={group.module} className="zh-perm-module">
                  <div className="zh-perm-module-head">
                    <strong>{group.module}</strong>
                    <Checkbox checked={allChecked} indeterminate={checkedCount > 0 && !allChecked} onChange={(e) => toggleModule(group, e.target.checked)}>
                      {checkedCount > 0 ? `已选 ${checkedCount} / ${codes.length}` : '全选'}
                    </Checkbox>
                  </div>
                  <Checkbox.Group value={selected} onChange={(values) => setSelected(values as string[])}>
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
            {!permissionLoading && filteredGroups.length === 0 && <EmptyState height={180} title="没有匹配的权限点" desc="请调整搜索关键词" />}
          </div>
        )}
      </TableCard>
    </div>
  )
}
