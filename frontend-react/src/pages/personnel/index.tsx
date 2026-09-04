import { useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import { App, Button, Form, Input, Modal, Select, Space, Switch, Table, Tag, TreeSelect } from 'antd'
import type { TableProps } from 'antd'
import { orgApi, organizationApi, schedulingApi, staffApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import type { OrganizationTreeResult, OrganizationUnit, OrganizationUnitType, StaffAccount, StaffAppointment, StaffRoleCode, SubjectInfo } from '@/types'
import { academicYearOptions } from '@/academicYear'
import { flattenOrganizationUnits, organizationExpandedKeys } from '@/pages/organization/tree-utils'
import PersonnelTree, { type PersonnelTreeKey } from './personnel-tree'

interface AccountForm { name: string; phone: string; password: string; roles?: StaffRoleCode[]; teacher_level?: string }
interface PersonEditForm {
  name: string
  phone: string
  roles?: StaffRoleCode[]
  teacher_level?: string
  unit_ids?: number[]
  position_code?: StaffAppointment['position_code']
}
interface UnitForm { name: string; unit_type: OrganizationUnitType; parent_id?: number; academic_year?: string; cohort_label?: string; grade_id?: number; subject_id?: number }
const TYPE_OPTIONS = [
  { label: '职能部门', value: 'department' }, { label: '年级部', value: 'grade_group' },
  { label: '学科组', value: 'subject_group' }, { label: '行政班', value: 'admin_class' },
]
const POSITION_LABEL: Record<StaffAppointment['position_code'], string> = {
  principal: '校长', academic_director: '教导主任', grade_director: '年级主任', head_teacher: '班主任',
  deputy_head_teacher: '副班主任', member: '组织成员',
}

export default function PersonnelView() {
  const { message, modal } = App.useApp()
  const [org, setOrg] = useState<OrganizationTreeResult>()
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [appointments, setAppointments] = useState<StaffAppointment[]>([])
  const [subjects, setSubjects] = useState<SubjectInfo[]>([])
  const [schoolGrades, setSchoolGrades] = useState<Array<{ id: number; level?: number; name: string }>>([])
  const [selectedKey, setSelectedKey] = useState<PersonnelTreeKey>('school')
  const [expandedKeys, setExpandedKeys] = useState<Key[]>(['school'])
  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [status, setStatus] = useState<string>()
  const [appliedStatus, setAppliedStatus] = useState<string>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [personEditOpen, setPersonEditOpen] = useState(false)
  const [accountKind, setAccountKind] = useState<'staff' | 'teacher'>('staff')
  const [unitOpen, setUnitOpen] = useState(false)
  const [editingPerson, setEditingPerson] = useState<StaffAccount>()
  const [editingUnit, setEditingUnit] = useState<OrganizationUnit>()
  const [accountForm] = Form.useForm<AccountForm>()
  const [personEditForm] = Form.useForm<PersonEditForm>()
  const [unitForm] = Form.useForm<UnitForm>()

  const load = async () => {
    setLoading(true)
    try {
      const [tree, staff, items, grades, subjectList] = await Promise.all([
        organizationApi.tree(),
        staffApi.list(),
        organizationApi.appointments(),
        orgApi.grades(),
        schedulingApi.subjects(),
      ])
      setOrg(tree)
      setAccounts(staff.accounts)
      setAppointments(items)
      setSchoolGrades(grades)
      setSubjects(subjectList)
      setExpandedKeys(['school', ...organizationExpandedKeys(tree.units)])
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员目录加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { void load() }, [])

  const unitTreeData = useMemo(() => {
    const toNodes = (items: OrganizationUnit[]): { title: string; value: number; children?: ReturnType<typeof toNodes> }[] =>
      items.filter((item) => item.status === 'active').map((item) => ({
        title: item.name,
        value: item.id,
        children: item.children?.length ? toNodes(item.children) : undefined,
      }))
    return toNodes(org?.units || [])
  }, [org])
  const units = useMemo(() => flattenOrganizationUnits(org?.units || []), [org])
  const selectedUnit = typeof selectedKey === 'number' ? units.find((item) => item.id === selectedKey) : undefined
  const yearOptions = useMemo(
    () => academicYearOptions([
      ...units.map((unit) => unit.academic_year),
      ...appointments.map((item) => item.academic_year),
    ]),
    [appointments, units],
  )
  const appointedIds = useMemo(() => new Set(appointments.map((item) => item.staff_id)), [appointments])
  const visibleAccounts = useMemo(() => accounts.filter((account) => {
    const inOrganization = selectedKey === 'school' || (selectedKey === 'unassigned'
      ? !appointedIds.has(account.id)
      : appointments.some((item) => item.organization_unit_id === selectedKey && item.staff_id === account.id))
    const query = appliedKeyword.trim().toLowerCase()
    return inOrganization && (!query || account.name.toLowerCase().includes(query) || account.phone.includes(query)) && (!appliedStatus || account.status === appliedStatus)
  }), [accounts, appointments, appointedIds, appliedKeyword, appliedStatus, selectedKey])
  const pagedAccounts = useMemo(
    () => visibleAccounts.slice((page - 1) * pageSize, page * pageSize),
    [visibleAccounts, page, pageSize],
  )
  useEffect(() => {
    setPage(1)
  }, [selectedKey, appliedKeyword, appliedStatus])
  const selectedLabel = selectedKey === 'school' ? (org?.school.name || '全校人员') : selectedKey === 'unassigned' ? '未分配组织' : selectedUnit?.name || '组织成员'
  const searchAccounts = () => {
    setAppliedKeyword(keyword)
    setAppliedStatus(status)
    setPage(1)
  }
  const resetFilters = () => {
    setKeyword('')
    setAppliedKeyword('')
    setStatus(undefined)
    setAppliedStatus(undefined)
    setPage(1)
  }

  const openCreateAccount = (kind: 'staff' | 'teacher') => {
    setAccountKind(kind)
    accountForm.resetFields()
    accountForm.setFieldsValue({ roles: kind === 'teacher' ? ['subject_teacher'] : [], teacher_level: kind === 'teacher' ? '普通教师' : undefined })
    setAccountOpen(true)
  }
  const createAccount = async () => {
    const values = await accountForm.validateFields().catch(() => null); if (!values) return
    setSaving(true)
    try {
      const roles = Array.from(new Set([...(values.roles || []), ...(accountKind === 'teacher' ? ['subject_teacher' as const] : [])]))
      await staffApi.create({ ...values, roles, teacher_level: accountKind === 'teacher' ? values.teacher_level : undefined })
      setAccountOpen(false)
      accountForm.resetFields()
      message.success(accountKind === 'teacher' ? '教师账号已创建' : '人员账号已创建')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '账号创建失败')
    } finally {
      setSaving(false)
    }
  }
  const toggleAccount = async (account: StaffAccount, enabled: boolean) => {
    try {
      await staffApi.updateStatus(account.id, enabled ? 'active' : 'disabled')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '状态更新失败')
    }
  }
  const openPersonEdit = (account: StaffAccount) => {
    if (account.is_school_admin) return
    personEditForm.setFieldsValue({
      name: account.name,
      phone: account.phone,
      roles: account.roles.filter((role): role is StaffRoleCode => role !== 'school_admin'),
      teacher_level: account.teacher_level || undefined,
      unit_ids: appointments.filter((item) => item.staff_id === account.id).map((item) => item.organization_unit_id),
      position_code: 'member',
    })
    setPersonEditOpen(true)
    setEditingPerson(account)
  }
  const savePersonEdit = async () => {
    if (!editingPerson) return
    const values = await personEditForm.validateFields().catch(() => null); if (!values) return
    setSaving(true)
    try {
      await staffApi.update(editingPerson.id, { name: values.name, phone: values.phone, roles: values.roles || [], teacher_level: values.teacher_level || null })
      const current = appointments.filter((item) => item.staff_id === editingPerson.id)
      const nextIds = new Set(values.unit_ids || [])
      const currentIds = new Set(current.map((item) => item.organization_unit_id))
      await Promise.all(current.filter((item) => !nextIds.has(item.organization_unit_id)).map((item) => organizationApi.deleteAppointment(item.id)))
      const position = values.position_code || 'member'
      await Promise.all([...nextIds].filter((id) => !currentIds.has(id)).map((organization_unit_id) =>
        organizationApi.createAppointment({
          organization_unit_id,
          staff_id: editingPerson.id,
          position_code: position,
          replace_grade_assignment: true,
        }),
      ))
      setPersonEditOpen(false)
      message.success('人员与组织归属已更新')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '人员信息保存失败')
    } finally {
      setSaving(false)
    }
  }
  const openUnit = (edit = false) => {
    const unit = edit ? selectedUnit : undefined
    setEditingUnit(unit)
    unitForm.setFieldsValue(unit
      ? {
          name: unit.name,
          unit_type: unit.unit_type,
          parent_id: unit.parent_id || undefined,
          academic_year: unit.academic_year || undefined,
          cohort_label: unit.cohort_label || undefined,
          grade_id: unit.grade_id || undefined,
          subject_id: unit.subject_id || undefined,
        }
      : {
          name: '',
          unit_type: 'department',
          parent_id: typeof selectedKey === 'number' ? selectedKey : undefined,
          grade_id: undefined,
          subject_id: undefined,
        })
    setUnitOpen(true)
  }
  const saveUnit = async () => {
    const values = await unitForm.validateFields().catch(() => null); if (!values) return
    setSaving(true)
    try {
      editingUnit ? await organizationApi.updateUnit(editingUnit.id, values) : await organizationApi.createUnit(values)
      setUnitOpen(false)
      message.success('组织信息已保存')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '组织保存失败')
    } finally {
      setSaving(false)
    }
  }
  const archiveUnit = () => selectedUnit && modal.confirm({
    title: `归档“${selectedUnit.name}”`,
    content: selectedUnit.unit_type === 'grade_group'
      ? '将同时归档该年级部的教师任职关系，教师账号和历史业务数据保留。'
      : '历史业务记录会保留，该组织不再出现在当前组织树。',
    okText: '确认归档',
    onOk: async () => {
      if (selectedUnit.unit_type === 'grade_group') await organizationApi.archiveUnitAppointments(selectedUnit.id)
      await organizationApi.updateUnit(selectedUnit.id, { status: 'archived' })
      setSelectedKey('school')
      await load()
    },
  })

  const removeAppointment = async (id: number) => {
    try {
      await organizationApi.deleteAppointment(id)
      message.success('组织任命已解除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '解除组织任命失败')
    }
  }

  const columns: TableProps<StaffAccount>['columns'] = [
    { title: '人员', dataIndex: 'name', render: (name, row) => <div className="zh-person-cell"><strong>{name}</strong><span>{row.is_school_admin ? '校长账号' : row.phone}</span></div> },
    { title: '所属组织', key: 'organization', render: (_, row) => {
      const items = appointments.filter((item) => item.staff_id === row.id)
      return items.length
        ? <Space size={[4, 4]} wrap>{items.map((item) => (
          <Tag key={item.id} closable onClose={(event) => { event.preventDefault(); void removeAppointment(item.id) }}>
            {item.organization_name} · {POSITION_LABEL[item.position_code]}
          </Tag>
        ))}</Space>
        : '未分配'
    } },
    { title: '岗位职责', key: 'roles', render: (_, row) => row.is_school_admin ? '校长管理员' : row.roles.length ? `${row.roles.length} 项职责` : '待配置' },
    { title: '账号状态', width: 120, render: (_, row) => <Switch checked={row.status === 'active'} disabled={row.is_school_admin} checkedChildren="启用" unCheckedChildren="停用" onChange={(value) => void toggleAccount(row, value)} /> },
    { title: '操作', key: 'action', width: 145, align: 'right', render: (_, row) => row.is_school_admin ? <span className="zh-locked">校长账号</span> : <Button type="link" size="small" onClick={() => openPersonEdit(row)}>编辑</Button> },
  ]

  return <div className="zh-page">
    <PageHeader
      title="人员账号"
      extra={(
        <Space>
          <Button onClick={() => openUnit(false)}>新建组织</Button>
          <Button type="primary" onClick={() => openCreateAccount('staff')}>新增人员</Button>
        </Space>
      )}
    />
    <p className="zh-page-desc">组织树是人员目录的浏览入口；选择组织即可查看成员，未归属人员集中显示在“未分配组织”。</p>
    <div className="personnel-workspace">
      <PersonnelTree
        data={org}
        appointments={appointments}
        totalCount={accounts.length}
        unassignedCount={accounts.filter((item) => !appointedIds.has(item.id)).length}
        selectedKey={selectedKey}
        expandedKeys={expandedKeys}
        onExpand={setExpandedKeys}
        onSelect={setSelectedKey}
      />
      <section className="personnel-directory" aria-label={`${selectedLabel}人员列表`}>
        <header className="personnel-directory-head">
          <div><span>当前范围</span><h3>{selectedLabel}</h3></div>
          {selectedUnit && (
            <Space>
              <Button size="small" onClick={() => openUnit(true)}>编辑组织</Button>
              <Button size="small" danger onClick={archiveUnit}>归档</Button>
            </Space>
          )}
        </header>
        <div className="personnel-filters">
          <Input allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索姓名或手机号" onPressEnter={searchAccounts} />
          <Select allowClear value={status} onChange={setStatus} placeholder="全部状态" options={[{ label: '启用', value: 'active' }, { label: '停用', value: 'disabled' }]} />
          <Button type="primary" onClick={searchAccounts}>查询</Button>
          <Button onClick={resetFilters}>重置查询</Button>
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={pagedAccounts}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: visibleAccounts.length,
            onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize) },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          locale={{ emptyText: <EmptyState icon="users" title="该范围暂无人员" desc="点「编辑」可把人员挂到左侧组织树上。" height={220} /> }}
        />
      </section>
    </div>
    <Modal title={accountKind === 'teacher' ? '新增教师账号' : '新增人员账号'} open={accountOpen} onCancel={() => setAccountOpen(false)} onOk={() => void createAccount()} confirmLoading={saving} okText="创建账号" forceRender>
      <Form form={accountForm} layout="vertical">
        <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="phone" label="登录手机号" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item>
        <Form.Item label="人员类型"><Select value={accountKind} onChange={(value) => openCreateAccount(value)} options={[{ value: 'staff', label: '普通人员' }, { value: 'teacher', label: '教师' }]} /></Form.Item>
        <Form.Item name="roles" label="职位角色"><Select mode="multiple" placeholder="选择职位角色" options={[{ value: 'academic_director', label: '教导主任' }, { value: 'head_teacher', label: '班主任' }, { value: 'subject_teacher', label: '任教老师' }]} /></Form.Item>
        {accountKind === 'teacher' && (
          <>
            <Form.Item label="教师职级" name="teacher_level" rules={[{ required: true, message: '请选择教师职级' }]}>
              <Select options={['特级教师', '正高级教师', '高级教师', '一级教师', '二级教师', '普通教师'].map((label) => ({ value: label, label }))} />
            </Form.Item>
            <p className="zh-page-desc">教师自动带上“任教老师”角色；教师职级可用于实验班等班级类型的分配策略。</p>
          </>
        )}
      </Form>
    </Modal>
    <Modal title={`编辑人员 · ${editingPerson?.name || ''}`} open={personEditOpen} onCancel={() => setPersonEditOpen(false)} onOk={() => void savePersonEdit()} confirmLoading={saving} okText="保存" cancelText="取消" forceRender>
      <Form form={personEditForm} layout="vertical">
        <Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="phone" label="登录手机号" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="roles" label="职位角色"><Select mode="multiple" placeholder="选择职位角色" options={[{ value: 'academic_director', label: '教导主任' }, { value: 'head_teacher', label: '班主任' }, { value: 'subject_teacher', label: '任教老师' }]} /></Form.Item>
        <Form.Item name="teacher_level" label="教师职级"><Select allowClear placeholder="非教师可留空" options={['特级教师', '正高级教师', '高级教师', '一级教师', '二级教师', '普通教师'].map((label) => ({ value: label, label }))} /></Form.Item>
        <Form.Item name="unit_ids" label="所属组织">
          <TreeSelect
            treeData={unitTreeData}
            allowClear
            multiple
            placeholder="选择教务处、年级部、教研组等，可多选"
            treeDefaultExpandAll
            showSearch
            treeNodeFilterProp="title"
            style={{ width: '100%' }}
          />
        </Form.Item>
        <Form.Item name="position_code" label="新加入组织时的岗位" extra="已有组织会保留原来的岗位；勾选新组织时用这里的岗位。">
          <Select options={Object.entries(POSITION_LABEL).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
      </Form>
    </Modal>
    <Modal title={editingUnit ? '编辑组织' : '新建组织'} open={unitOpen} onCancel={() => setUnitOpen(false)} onOk={() => void saveUnit()} confirmLoading={saving} okText="保存" forceRender>
      <Form form={unitForm} layout="vertical">
        <Form.Item name="name" label="组织名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="unit_type" label="组织类型" rules={[{ required: true }]}><Select disabled={!!editingUnit} options={TYPE_OPTIONS} /></Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.unit_type !== next.unit_type}>
          {({ getFieldValue }) => getFieldValue('unit_type') === 'subject_group' ? (
            <Form.Item name="subject_id" label="关联科目" rules={[{ required: true, message: '请选择学科组关联的科目' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择该学科组负责的科目" options={subjects.map((subject) => ({ value: subject.id, label: subject.name }))} />
            </Form.Item>
          ) : null}
        </Form.Item>
        <Form.Item name="parent_id" label="上级组织">
          <Select allowClear options={units.filter((item) => item.id !== editingUnit?.id).map((unit) => ({ label: unit.name, value: unit.id }))} />
        </Form.Item>
        <div className="zh-form-grid">
          <Form.Item name="academic_year" label="所属学年"><Select allowClear placeholder="选择学年；长期组织留空" options={yearOptions} /></Form.Item>
          <Form.Item name="cohort_label" label="对应届"><Input placeholder="例如：2029届" /></Form.Item>
        </div>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.unit_type !== next.unit_type}>
          {({ getFieldValue }) => getFieldValue('unit_type') === 'grade_group' ? (
            <Form.Item name="grade_id" label="对应年级" rules={[{ required: true, message: '请选择对应年级' }]}>
              <Select placeholder="选择高一年级 / 高二年级 / 高三年级" options={schoolGrades.map((grade) => ({ label: grade.name, value: grade.id }))} />
            </Form.Item>
          ) : null}
        </Form.Item>
      </Form>
    </Modal>
  </div>
}
