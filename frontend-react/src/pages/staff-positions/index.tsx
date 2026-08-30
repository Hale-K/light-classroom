import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { organizationApi, schedulingApi, staffApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import { STAFF_ROLE_DICT } from '@/types/dict'
import type { OrganizationUnit, StaffAccount, StaffAppointment, StaffRoleCode, StaffRoleOption, SubjectInfo } from '@/types'
import { diffTeacherSubjectAppointments } from './teacher-subjects'

interface PositionFormValues {
  roles: StaffRoleCode[]
  subject_unit_ids?: number[]
  organization_unit_id?: number
  position_code?: StaffAppointment['position_code']
  academic_year?: string
}
const POSITION_LABEL: Record<StaffAppointment['position_code'], string> = {
  principal: '校长',
  academic_director: '教导主任', grade_director: '年级主任', head_teacher: '班主任',
  deputy_head_teacher: '副班主任', member: '组织成员',
}
function flatten(units: OrganizationUnit[]): OrganizationUnit[] {
  return units.flatMap((unit) => [unit, ...flatten(unit.children)])
}

export default function StaffPositionsView() {
  const { message } = App.useApp()
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [roles, setRoles] = useState<StaffRoleOption[]>([])
  const [units, setUnits] = useState<OrganizationUnit[]>([])
  const [subjects, setSubjects] = useState<SubjectInfo[]>([])
  const [appointments, setAppointments] = useState<StaffAppointment[]>([])
  const [editing, setEditing] = useState<StaffAccount>()
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<PositionFormValues>()

  const load = async () => {
    setLoading(true)
    try {
      const [directory, tree, assigned, subjectList] = await Promise.all([
        staffApi.list(), organizationApi.tree(), organizationApi.appointments(), schedulingApi.subjects(),
      ])
      setAccounts(directory.accounts); setRoles(directory.roles); setUnits(flatten(tree.units)); setAppointments(assigned); setSubjects(subjectList)
    } catch (error) { message.error(error instanceof Error ? error.message : '岗位配置加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const query = keyword.trim().toLowerCase()
    return accounts.filter((item) => !query || item.name.toLowerCase().includes(query) || item.phone.includes(query))
  }, [accounts, keyword])

  const subjectUnits = useMemo(
    () => units.filter((unit) => unit.unit_type === 'subject_group' && unit.status === 'active' && unit.subject_id != null),
    [units],
  )
  const subjectNameById = useMemo(() => new Map(subjects.map((subject) => [subject.id, subject.name])), [subjects])

  const open = (account: StaffAccount) => {
    setEditing(account)
    form.setFieldsValue({
      roles: account.roles.filter((role): role is StaffRoleCode => role !== 'school_admin'),
      subject_unit_ids: appointments
        .filter((entry) => entry.staff_id === account.id && entry.position_code === 'member' && entry.status === 'active' && subjectUnits.some((unit) => unit.id === entry.organization_unit_id))
        .map((entry) => entry.organization_unit_id),
      organization_unit_id: undefined, position_code: undefined, academic_year: undefined,
    })
  }
  const save = async () => {
    if (!editing) return
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    if (!!values.organization_unit_id !== !!values.position_code) {
      message.warning('组织和岗位需要同时选择'); return
    }
    setSaving(true)
    try {
      await staffApi.updateRoles(editing.id, values.roles ?? [])
      const subjectSync = diffTeacherSubjectAppointments(
        appointments,
        editing.id,
        subjectUnits.map((unit) => unit.id),
        values.subject_unit_ids ?? [],
      )
      await Promise.all(subjectSync.toCreate.map((organizationUnitId) => organizationApi.createAppointment({
        organization_unit_id: organizationUnitId,
        staff_id: editing.id,
        position_code: 'member',
      })))
      await Promise.all(subjectSync.toRemove.map((appointmentId) => organizationApi.deleteAppointment(appointmentId)))
      if (values.organization_unit_id && values.position_code) {
        await organizationApi.createAppointment({
          organization_unit_id: values.organization_unit_id, staff_id: editing.id,
          position_code: values.position_code, academic_year: values.academic_year,
        })
      }
      message.success('岗位、权限与任教科目已更新'); setEditing(undefined); await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '岗位配置保存失败') }
    finally { setSaving(false) }
  }
  const removeAppointment = async (id: number) => {
    try { await organizationApi.deleteAppointment(id); await load(); message.success('岗位任命已解除') }
    catch (error) { message.error(error instanceof Error ? error.message : '解除岗位失败') }
  }

  const columns: TableProps<StaffAccount>['columns'] = [
    { title: '人员', key: 'person', width: 180, render: (_, item) => <div className="zh-person-cell"><strong>{item.name}</strong><span>{item.phone}</span></div> },
    { title: '系统职责', key: 'roles', width: 260, render: (_, item) => <div className="zh-role-tags">
      {item.roles.map((role) => <DictTag key={role} dict={STAFF_ROLE_DICT} value={role} />)}
      {!item.roles.length && <span className="zh-account-pending">未配置</span>}
    </div> },
    { title: '任教科目', key: 'subjects', width: 260, render: (_, item) => {
      const subjects = appointments
        .filter((entry) => entry.staff_id === item.id && entry.position_code === 'member' && entry.status === 'active')
        .map((entry) => {
          const unit = subjectUnits.find((item) => item.id === entry.organization_unit_id)
          return unit?.subject_id ? subjectNameById.get(unit.subject_id) : undefined
        })
        .filter((name): name is string => !!name)
      return subjects.length ? <Space size={[4, 4]} wrap>{subjects.map((name) => <Tag key={name} color="blue">{name}</Tag>)}</Space> : <span className="zh-account-pending">未配置</span>
    } },
    { title: '组织岗位', key: 'appointments', render: (_, item) => <div className="zh-position-tags">
      {appointments.filter((entry) => entry.staff_id === item.id).map((entry) => <Tag key={entry.id} closable
        onClose={(event) => { event.preventDefault(); void removeAppointment(entry.id) }}>
        {entry.organization_name} · {POSITION_LABEL[entry.position_code]}
      </Tag>)}
      {!appointments.some((entry) => entry.staff_id === item.id) && <span className="zh-account-pending">未任命组织岗位</span>}
    </div> },
    { title: '操作', key: 'action', width: 110, align: 'right', render: (_, item) => item.is_school_admin
      ? <span className="zh-locked">校长账号</span>
      : <Button type="link" size="small" onClick={() => open(item)}>配置岗位</Button> },
  ]

  return <div className="zh-page">
    <PageHeader title="岗位与权限" />
    <p className="zh-page-desc">系统职责决定可使用的业务功能；组织岗位决定人员在哪个部门、年级或班级承担责任。</p>
    <FilterCard><div className="zh-filter-row"><label className="zh-filter-field"><span>人员</span>
      <Input value={keyword} allowClear placeholder="姓名或手机号" style={{ width: 260 }} onChange={(event) => setKeyword(event.target.value)} />
    </label><span className="zh-filter-count">共 {filtered.length} 人</span></div></FilterCard>
    <TableCard><Table rowKey="id" columns={columns} dataSource={filtered} loading={loading} pagination={{ pageSize: 10, showSizeChanger: false }}
      locale={{ emptyText: <EmptyState height={240} title="暂无可配置人员" desc="请先在“人员账号”中创建教职工账号" /> }} /></TableCard>
    <Modal title={editing ? `配置岗位 · ${editing.name}` : '配置岗位'} open={!!editing} onCancel={() => setEditing(undefined)}
      onOk={() => void save()} confirmLoading={saving} okText="保存配置" cancelText="取消" width={560} forceRender>
      <Form form={form} layout="vertical">
        <Form.Item name="roles" label="系统职责"><Select mode="multiple" allowClear placeholder="可暂不分配"
          options={roles.map((role) => ({ value: role.code, label: role.name }))} /></Form.Item>
        <Form.Item name="subject_unit_ids" label="任教科目">
          <Select
            mode="multiple"
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder={subjectUnits.length ? '选择教师可以教授的科目' : '请先在组织机构中创建学科组'}
            options={subjectUnits.map((unit) => ({ value: unit.id, label: `${subjectNameById.get(unit.subject_id || -1)}（${unit.name}）` }))}
            disabled={!subjectUnits.length}
          />
        </Form.Item>
        <p className="zh-page-desc" style={{ marginTop: -8 }}>这里只维护教师可教科目；具体分配到哪个班级，请在“排课管理”的任教关系中设置。</p>
        <div className="zh-position-divider"><span>组织岗位任命</span><small>可选；未选择时只更新系统职责</small></div>
        <Form.Item name="organization_unit_id" label="所属组织"><Select allowClear showSearch optionFilterProp="label"
          placeholder={units.length ? '选择组织节点' : '请先创建组织机构'} disabled={!units.length}
          options={units.map((unit) => ({ value: unit.id, label: unit.name }))} /></Form.Item>
        <div className="zh-form-grid">
          <Form.Item name="position_code" label="担任岗位"><Select allowClear placeholder="选择岗位"
            options={Object.entries(POSITION_LABEL).filter(([value]) => value !== 'principal' || editing?.is_school_admin).map(([value, label]) => ({ value, label }))} /></Form.Item>
          <Form.Item name="academic_year" label="任职学年"><Input placeholder="长期岗位可留空" /></Form.Item>
        </div>
      </Form>
    </Modal>
  </div>
}
