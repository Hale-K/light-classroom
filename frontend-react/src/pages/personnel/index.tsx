import { useEffect, useMemo, useState } from 'react'
import type { Key } from 'react'
import { App, Button, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { orgApi, organizationApi, staffApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import type { OrganizationTreeResult, OrganizationUnit, OrganizationUnitType, StaffAccount, StaffAppointment, StaffRoleCode, Student, StudentGradeMembership } from '@/types'
import { academicYearOptions } from '@/academicYear'
import { flattenOrganizationUnits, organizationExpandedKeys } from '@/pages/organization/tree-utils'
import PersonnelTree, { type PersonnelTreeKey } from './personnel-tree'
import { calculateRequiredTeacherCount } from './staffing'

interface AccountForm { name: string; phone: string; password: string; roles?: StaffRoleCode[]; teacher_level?: string }
interface UnitForm { name: string; unit_type: OrganizationUnitType; parent_id?: number; academic_year?: string; cohort_label?: string; grade_id?: number }
interface TeacherAllocationForm { allocation_mode?: 'batch' | 'single'; teacher_id?: number; source_unit_ids?: number[]; organization_unit_id?: number; position_code: StaffAppointment['position_code']; academic_year?: string; class_count?: number; weekly_periods?: number; max_weekly_periods?: number; max_classes_per_teacher?: number; max_classes_per_head_teacher?: number }
const TYPE_OPTIONS = [
  { label: '职能部门', value: 'department' }, { label: '年级部', value: 'grade_group' },
  { label: '学科组', value: 'subject_group' }, { label: '行政班', value: 'admin_class' },
]
const POSITION_LABEL: Record<StaffAppointment['position_code'], string> = {
  principal: '校长', academic_director: '教导主任', grade_director: '年级主任', head_teacher: '班主任',
  deputy_head_teacher: '副班主任', member: '组织成员',
}
const SUBJECT_HOURS: Record<string, number> = { 语文: 5, 数学: 5, 英语: 5, 物理: 3, 化学: 3, 生物: 2, 政治: 2, 历史: 2, 地理: 2, 体育: 1 }
const HEAD_TEACHER_SUBJECTS = new Set(['语文', '数学', '英语', '物理', '历史', '化学', '生物', '政治', '地理'])
const HEAD_TEACHER_PRIORITY_SUBJECTS = new Set(['语文', '数学', '英语'])

export default function PersonnelView() {
  const { message, modal } = App.useApp()
  const [org, setOrg] = useState<OrganizationTreeResult>()
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [appointments, setAppointments] = useState<StaffAppointment[]>([])
  const [includeArchivedAppointments, setIncludeArchivedAppointments] = useState(false)
  const [schoolGrades, setSchoolGrades] = useState<Array<{ id: number; level?: number; name: string }>>([])
  const [schoolClasses, setSchoolClasses] = useState<Array<{ id: number; grade_id: number; student_count?: number; head_teacher_id?: number }>>([])
  const [schoolStudents, setSchoolStudents] = useState<Student[]>([])
  const [studentGradeMemberships, setStudentGradeMemberships] = useState<StudentGradeMembership[]>([])
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
  const [teacherAllocationOpen, setTeacherAllocationOpen] = useState(false)
  const [teacherPlanReady, setTeacherPlanReady] = useState(false)
  const [editingPerson, setEditingPerson] = useState<StaffAccount>()
  const [editingUnit, setEditingUnit] = useState<OrganizationUnit>()
  const [accountForm] = Form.useForm<AccountForm>()
  const [personEditForm] = Form.useForm<AccountForm>()
  const [unitForm] = Form.useForm<UnitForm>()
  const [teacherAllocationForm] = Form.useForm<TeacherAllocationForm>()

  const load = async () => {
    setLoading(true)
    try {
      const [tree, staff, items, grades, classes, students, memberships] = await Promise.all([organizationApi.tree(), staffApi.list(), organizationApi.appointments(includeArchivedAppointments), orgApi.grades(), orgApi.classes(), orgApi.students(), orgApi.studentGradeMemberships()])
      setOrg(tree); setAccounts(staff.accounts); setAppointments(items); setSchoolGrades(grades); setSchoolClasses(classes); setSchoolStudents(students); setStudentGradeMemberships(memberships)
      setExpandedKeys(['school', ...organizationExpandedKeys(tree.units)])
    } catch (error) { message.error(error instanceof Error ? error.message : '人员目录加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [includeArchivedAppointments])

  const units = useMemo(() => flattenOrganizationUnits(org?.units || []), [org])
  // 年级部 = 年级管理中心下的子单元(兼容历史数据里类型为 grade_group 的单元)
  const gradeCenterId = units.find((item) => item.name === '年级管理中心')?.id
  const gradeUnitOptions = units
    .filter((item) => item.status === 'active' && (item.parent_id === gradeCenterId || item.unit_type === 'grade_group'))
    .map((item) => ({ value: item.id, label: item.name }))
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
    try { const roles = Array.from(new Set([...(values.roles || []), ...(accountKind === 'teacher' ? ['subject_teacher' as const] : [])])); await staffApi.create({ ...values, roles, teacher_level: accountKind === 'teacher' ? values.teacher_level : undefined }); setAccountOpen(false); accountForm.resetFields(); message.success(accountKind === 'teacher' ? '教师账号已创建' : '人员账号已创建'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '账号创建失败') }
    finally { setSaving(false) }
  }
  const toggleAccount = async (account: StaffAccount, enabled: boolean) => {
    try { await staffApi.updateStatus(account.id, enabled ? 'active' : 'disabled'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '状态更新失败') }
  }
  const openPersonEdit = (account: StaffAccount) => {
    if (account.is_school_admin) return
    personEditForm.setFieldsValue({ name: account.name, phone: account.phone, roles: account.roles.filter((role): role is StaffRoleCode => role !== 'school_admin'), teacher_level: account.teacher_level || undefined })
    setPersonEditOpen(true)
    setEditingPerson(account)
  }
  const savePersonEdit = async () => {
    if (!editingPerson) return
    const values = await personEditForm.validateFields().catch(() => null); if (!values) return
    setSaving(true)
    try { await staffApi.update(editingPerson.id, { ...values, roles: values.roles || [], teacher_level: values.teacher_level || null }); setPersonEditOpen(false); message.success('人员信息已更新'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '人员信息保存失败') }
    finally { setSaving(false) }
  }
  const openUnit = (edit = false) => {
    const unit = edit ? selectedUnit : undefined; setEditingUnit(unit)
    unitForm.setFieldsValue(unit ? { name: unit.name, unit_type: unit.unit_type, parent_id: unit.parent_id || undefined, academic_year: unit.academic_year || undefined, cohort_label: unit.cohort_label || undefined, grade_id: unit.grade_id || undefined } : { name: '', unit_type: 'department', parent_id: typeof selectedKey === 'number' ? selectedKey : undefined, grade_id: undefined })
    setUnitOpen(true)
  }
  const saveUnit = async () => {
    const values = await unitForm.validateFields().catch(() => null); if (!values) return
    setSaving(true)
    try { editingUnit ? await organizationApi.updateUnit(editingUnit.id, values) : await organizationApi.createUnit(values); setUnitOpen(false); message.success('组织信息已保存'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '组织保存失败') }
    finally { setSaving(false) }
  }
  const archiveUnit = () => selectedUnit && modal.confirm({
    title: `归档“${selectedUnit.name}”`,
    content: selectedUnit.unit_type === 'grade_group' ? '将同时归档该年级部的教师任职关系，教师账号和历史业务数据保留。' : '历史业务记录会保留，该组织不再出现在当前组织树。',
    okText: '确认归档',
    onOk: async () => {
      if (selectedUnit.unit_type === 'grade_group') await organizationApi.archiveUnitAppointments(selectedUnit.id)
      await organizationApi.updateUnit(selectedUnit.id, { status: 'archived' })
      setSelectedKey('school')
      await load()
    },
  })

  const openTeacherAllocation = () => {
    teacherAllocationForm.resetFields()
    teacherAllocationForm.setFieldsValue({ allocation_mode: 'batch', position_code: 'member', academic_year: yearOptions[0]?.value, max_classes_per_teacher: 3, max_classes_per_head_teacher: 2, max_weekly_periods: 20, weekly_periods: 5 })
    setTeacherPlanReady(false)
    setTeacherAllocationOpen(true)
  }

  const teacherPlanValues = Form.useWatch([], teacherAllocationForm) || {}
  const allocationMode = teacherPlanValues.allocation_mode || 'batch'
  const getTargetGradeStats = (unitId?: number) => {
    const target = units.find((item) => item.id === unitId)
    const level = target?.name.includes('高一') ? 1 : target?.name.includes('高二') ? 2 : target?.name.includes('高三') ? 3 : undefined
    const gradeIds = new Set(schoolGrades.filter((item) => item.level === level).map((item) => item.id))
    const targetClasses = schoolClasses.filter((item) => gradeIds.has(item.grade_id))
    const academicYear = teacherPlanValues.academic_year
    const membershipStudents = studentGradeMemberships.filter((membership) => membership.status === 'active' && membership.grade_unit_id === unitId && (!academicYear || membership.academic_year === academicYear))
    const studentCount = membershipStudents.length > 0
      ? membershipStudents.length
      : schoolStudents.filter((student) => gradeIds.has(student.grade_id || -1)).length
    return {
      classCount: targetClasses.length,
      studentCount,
      headTeacherIds: new Set(targetClasses.flatMap((item) => item.head_teacher_id ? [item.head_teacher_id] : [])),
    }
  }
  const targetGradeStats = useMemo(() => {
    return getTargetGradeStats(teacherPlanValues.organization_unit_id)
  }, [schoolClasses, schoolGrades, schoolStudents, studentGradeMemberships, teacherPlanValues.academic_year, teacherPlanValues.organization_unit_id, units])
  const subjectStaffStats = useMemo(() => Object.entries(SUBJECT_HOURS).map(([subject, weeklyPeriods]) => {
    const subjectUnit = units.find((item) => item.unit_type === 'subject_group' && item.name.includes(subject))
    const selectedSourceIds = new Set<number>(teacherPlanValues.source_unit_ids || [])
    const sourceSelected = !!subjectUnit && selectedSourceIds.has(subjectUnit.id)
    const subjectTeacherIds = new Set(subjectUnit ? appointments.filter((item) => item.organization_unit_id === subjectUnit.id && item.status === 'active').map((item) => item.staff_id) : [])
    const gradeUnitIds = new Set(units.filter((item) => item.unit_type === 'grade_group').map((item) => item.id))
    const lockedInOtherGrade = new Set(appointments.filter((item) => item.status === 'active' && gradeUnitIds.has(item.organization_unit_id) && item.organization_unit_id !== teacherPlanValues.organization_unit_id).map((item) => item.staff_id))
    const targetTeacherIds = new Set(appointments.filter((item) => item.organization_unit_id === teacherPlanValues.organization_unit_id && item.status === 'active' && subjectTeacherIds.has(item.staff_id)).map((item) => item.staff_id))
    const availableSubjectTeachers = sourceSelected
      ? accounts.filter((account) => account.status === 'active' && !account.is_school_admin && subjectTeacherIds.has(account.id) && !lockedInOtherGrade.has(account.id))
      : []
    const available = availableSubjectTeachers.length
    const current = accounts.filter((account) => account.status === 'active' && subjectTeacherIds.has(account.id) && targetTeacherIds.has(account.id)).length
    const totalPeriods = targetGradeStats.classCount * weeklyPeriods
    const byWorkload = Math.ceil(totalPeriods / (teacherPlanValues.max_weekly_periods || 20))
    const headTeachers = HEAD_TEACHER_SUBJECTS.has(subject)
      ? availableSubjectTeachers.filter((account) => account.roles.includes('head_teacher')).length
      : 0
    const plan = calculateRequiredTeacherCount({
      classCount: targetGradeStats.classCount,
      headTeacherCount: headTeachers,
      maxClassesPerHeadTeacher: Math.min(teacherPlanValues.max_classes_per_head_teacher || 2, Math.floor((teacherPlanValues.max_weekly_periods || 20) / weeklyPeriods)),
      maxClassesPerTeacher: Math.min(teacherPlanValues.max_classes_per_teacher || 3, Math.floor((teacherPlanValues.max_weekly_periods || 20) / weeklyPeriods)),
    })
    const recommended = Math.max(byWorkload, plan.requiredTeacherCount)
    return { subject, weeklyPeriods, totalPeriods, available, current, headTeachers, ...plan, recommended, adjustment: recommended - current, shortage: sourceSelected ? Math.max(0, recommended - available) : 0, sourceSelected }
  }), [accounts, appointments, targetGradeStats, teacherPlanValues.max_classes_per_head_teacher, teacherPlanValues.max_classes_per_teacher, teacherPlanValues.max_weekly_periods, teacherPlanValues.organization_unit_id, teacherPlanValues.source_unit_ids, units])
  const headTeacherStats = useMemo(() => {
    const selectedSourceIds = new Set<number>(teacherPlanValues.source_unit_ids || [])
    const selectedSourceTeacherIds = new Set(
      appointments
        .filter((item) => item.status === 'active' && selectedSourceIds.has(item.organization_unit_id))
        .map((item) => item.staff_id),
    )
    const priorityTeacherIds = new Set(
      appointments
        .filter((item) => item.status === 'active' && selectedSourceIds.has(item.organization_unit_id))
        .filter((item) => {
          const sourceUnit = units.find((unit) => unit.id === item.organization_unit_id)
          return sourceUnit && [...HEAD_TEACHER_PRIORITY_SUBJECTS].some((subject) => sourceUnit.name.includes(subject))
        })
        .map((item) => item.staff_id),
    )
    const gradeUnitIds = new Set(units.filter((item) => item.unit_type === 'grade_group').map((item) => item.id))
    const lockedInOtherGrade = new Set(
      appointments
        .filter((item) => item.status === 'active' && gradeUnitIds.has(item.organization_unit_id) && item.organization_unit_id !== teacherPlanValues.organization_unit_id)
        .map((item) => item.staff_id),
    )
    const availableTeacher = (account: StaffAccount) => account.status === 'active' && !account.is_school_admin && account.roles.includes('subject_teacher') && account.roles.includes('head_teacher') && selectedSourceTeacherIds.has(account.id) && !lockedInOtherGrade.has(account.id)
    const available = selectedSourceIds.size
      ? accounts.filter(availableTeacher).length
      : 0
    const priorityAvailable = selectedSourceIds.size ? accounts.filter((account) => availableTeacher(account) && priorityTeacherIds.has(account.id)).length : 0
    const required = targetGradeStats.classCount
    const current = targetGradeStats.headTeacherIds.size
    return {
      required,
      current,
      available,
      priorityAvailable,
      fallbackRequired: Math.max(0, targetGradeStats.classCount - priorityAvailable),
      recommended: required,
      shortage: selectedSourceIds.size ? Math.max(0, required - available) : 0,
      adjustment: required - current,
      sourceSelected: selectedSourceIds.size > 0,
    }
  }, [accounts, appointments, targetGradeStats, teacherPlanValues.organization_unit_id, teacherPlanValues.source_unit_ids, units])
  const staffingSummary = useMemo(() => {
    const summary = { current: 0, recommended: 0, add: 0, release: 0, shortage: 0 }
    subjectStaffStats.filter((row) => row.sourceSelected).forEach((row) => {
      summary.current += row.current
      summary.recommended += row.recommended
      summary.add += Math.max(0, row.adjustment)
      summary.release += Math.max(0, -row.adjustment)
      summary.shortage += row.shortage
    })
    return {
      ...summary,
      headCurrent: headTeacherStats.current,
      headRecommended: headTeacherStats.recommended,
      headAdd: Math.max(0, headTeacherStats.adjustment),
      headRelease: Math.max(0, -headTeacherStats.adjustment),
      headShortage: headTeacherStats.shortage,
    }
  }, [headTeacherStats, subjectStaffStats])

  const previewTeacherAllocation = async () => {
    const values = await teacherAllocationForm.validateFields().catch(() => null)
    if (!values || !targetGradeStats.classCount || !values.weekly_periods || !values.max_weekly_periods || !values.max_classes_per_teacher || (allocationMode === 'single' && !values.teacher_id)) return
    setTeacherPlanReady(true)
  }

  const applyTeacherAllocation = async () => {
    const values = await teacherAllocationForm.validateFields().catch(() => null)
    const targetUnitId = values?.organization_unit_id
    const sourceUnitIds = new Set<number>(values?.source_unit_ids || [])
    if (!values || !targetUnitId || !sourceUnitIds.size) return
    setSaving(true)
    let createdCount = 0
    const shortages: string[] = []
    try {
      const targetGradeStaffIds = new Set(
        appointments.filter((item) => item.organization_unit_id === targetUnitId && item.status === 'active').map((item) => item.staff_id),
      )
      const gradeUnitIds = new Set(units.filter((item) => item.unit_type === 'grade_group').map((item) => item.id))
      const lockedInOtherGrade = new Set(
        appointments
          .filter((item) => item.status === 'active' && gradeUnitIds.has(item.organization_unit_id) && item.organization_unit_id !== targetUnitId)
          .map((item) => item.staff_id),
      )
      const headTeacherIds = targetGradeStats.headTeacherIds

      const plans: Array<{ source_unit_id: number; teacher_ids: number[]; required_count: number }> = []
      for (const row of subjectStaffStats) {
        const sourceUnit = units.find((item) => item.unit_type === 'subject_group' && item.name.includes(row.subject))
        if (!sourceUnit || !sourceUnitIds.has(sourceUnit.id)) continue
        const sourceTeacherIds = new Set(appointments.filter((item) => item.organization_unit_id === sourceUnit.id && item.status === 'active').map((item) => item.staff_id))
        const currentIds = new Set(
          appointments.filter((item) => item.organization_unit_id === targetUnitId && item.status === 'active' && sourceTeacherIds.has(item.staff_id)).map((item) => item.staff_id),
        )
        const need = Math.max(0, row.recommended - currentIds.size)
        if (!need) continue
        const candidates = accounts
          .filter((account) => account.status === 'active' && !account.is_school_admin && sourceTeacherIds.has(account.id) && !targetGradeStaffIds.has(account.id) && !lockedInOtherGrade.has(account.id))
          .sort((left, right) => Number(headTeacherIds.has(right.id)) - Number(headTeacherIds.has(left.id)) || left.id - right.id)
        const selected = candidates.slice(0, need)
        selected.forEach((teacher) => {
          targetGradeStaffIds.add(teacher.id)
        })
        plans.push({ source_unit_id: sourceUnit.id, teacher_ids: selected.map((teacher) => teacher.id), required_count: row.recommended })
        if (selected.length < need) shortages.push(`${row.subject}：还缺 ${need - selected.length} 人`)
      }
      if (shortages.length) {
        message.error(`无法安排：${shortages.join('、')}`)
        return
      }
      const result = await organizationApi.autoAllocateAppointments({
        target_unit_id: targetUnitId,
        academic_year: values.academic_year,
        position_code: values.position_code || 'member',
        plans,
      })
      createdCount = result.created_count
      setTeacherAllocationOpen(false)
      await load()
      message.success(`已自动安排 ${createdCount} 人到目标年级部`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : `自动安排失败，已完成 ${createdCount} 人`)
      await load()
    } finally { setSaving(false) }
  }

  const removeAppointment = async (id: number) => {
    try { await organizationApi.deleteAppointment(id); message.success('组织任命已解除'); await load() }
    catch (error) { message.error(error instanceof Error ? error.message : '解除组织任命失败') }
  }

  const columns: TableProps<StaffAccount>['columns'] = [
    { title: '人员', dataIndex: 'name', render: (name, row) => <div className="zh-person-cell"><strong>{name}</strong><span>{row.is_school_admin ? '校长账号' : row.phone}</span></div> },
    { title: '所属组织', key: 'organization', render: (_, row) => { const items = appointments.filter((item) => item.staff_id === row.id); return items.length ? <Space size={[4, 4]} wrap>{items.map((item) => <Tag key={item.id} closable onClose={(event) => { event.preventDefault(); void removeAppointment(item.id) }}>{item.organization_name} · {POSITION_LABEL[item.position_code]}</Tag>)}</Space> : '未分配' } },
    { title: '岗位职责', key: 'roles', render: (_, row) => row.is_school_admin ? '校长管理员' : row.roles.length ? `${row.roles.length} 项职责` : '待配置' },
    { title: '账号状态', width: 120, render: (_, row) => <Switch checked={row.status === 'active'} disabled={row.is_school_admin} checkedChildren="启用" unCheckedChildren="停用" onChange={(value) => void toggleAccount(row, value)} /> },
    { title: '操作', key: 'action', width: 145, align: 'right', render: (_, row) => row.is_school_admin ? <span className="zh-locked">校长账号</span> : <Button type="link" size="small" onClick={() => openPersonEdit(row)}>编辑</Button> },
  ]

  return <div className="zh-page">
    <PageHeader title="人员账号" extra={<Space><Switch checked={includeArchivedAppointments} checkedChildren="含历史任职" unCheckedChildren="当前任职" onChange={setIncludeArchivedAppointments} /><Button onClick={openTeacherAllocation}>师资调整</Button><Button onClick={() => openUnit(false)}>新建组织</Button><Button type="primary" onClick={() => openCreateAccount('staff')}>新增人员</Button></Space>} />
    <p className="zh-page-desc">组织树是人员目录的浏览入口；选择组织即可查看成员，未归属人员集中显示在“未分配组织”。</p>
    <div className="personnel-workspace">
      <PersonnelTree data={org} appointments={appointments} totalCount={accounts.length} unassignedCount={accounts.filter((item) => !appointedIds.has(item.id)).length}
        selectedKey={selectedKey} expandedKeys={expandedKeys} onExpand={setExpandedKeys} onSelect={setSelectedKey} />
      <section className="personnel-directory" aria-label={`${selectedLabel}人员列表`}>
        <header className="personnel-directory-head"><div><span>当前范围</span><h3>{selectedLabel}</h3></div>{selectedUnit && <Space><Button size="small" onClick={() => openUnit(true)}>编辑组织</Button><Button size="small" danger onClick={archiveUnit}>归档</Button></Space>}</header>
        <div className="personnel-filters"><Input allowClear value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索姓名或手机号" onPressEnter={searchAccounts} /><Select allowClear value={status} onChange={setStatus} placeholder="全部状态" options={[{ label: '启用', value: 'active' }, { label: '停用', value: 'disabled' }]} /><Button type="primary" onClick={searchAccounts}>查询</Button><Button onClick={resetFilters}>重置查询</Button></div>
        <Table rowKey="id" columns={columns} dataSource={pagedAccounts} loading={loading} pagination={{
          current: page,
          pageSize,
          total: visibleAccounts.length,
          onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize) },
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }} locale={{ emptyText: <EmptyState icon="users" title="该范围暂无人员" desc="新增人员后，可在“岗位与权限”中分配到当前组织。" height={220} /> }} />
      </section>
    </div>
    <Modal title={accountKind === 'teacher' ? '新增教师账号' : '新增人员账号'} open={accountOpen} onCancel={() => setAccountOpen(false)} onOk={() => void createAccount()} confirmLoading={saving} okText="创建账号" forceRender><Form form={accountForm} layout="vertical"><Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="phone" label="登录手机号" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="password" label="初始密码" rules={[{ required: true, min: 6 }]}><Input.Password /></Form.Item><Form.Item label="人员类型"><Select value={accountKind} onChange={(value) => openCreateAccount(value)} options={[{ value: 'staff', label: '普通人员' }, { value: 'teacher', label: '教师' }]} /></Form.Item><Form.Item name="roles" label="职位角色"><Select mode="multiple" placeholder="选择职位角色" options={[{ value: 'academic_director', label: '教导主任' }, { value: 'head_teacher', label: '班主任' }, { value: 'subject_teacher', label: '任教老师' }]} /></Form.Item>{accountKind === 'teacher' && <><Form.Item label="教师职级" name="teacher_level" rules={[{ required: true, message: '请选择教师职级' }]}><Select options={['特级教师', '正高级教师', '高级教师', '一级教师', '二级教师', '普通教师'].map((label) => ({ value: label, label }))} /></Form.Item><p className="zh-page-desc">教师自动带上“任教老师”角色；教师职级可用于实验班等班级类型的分配策略。</p></>}</Form></Modal>
    <Modal title={`编辑人员 · ${editingPerson?.name || ''}`} open={personEditOpen} onCancel={() => setPersonEditOpen(false)} onOk={() => void savePersonEdit()} confirmLoading={saving} okText="保存" cancelText="取消" forceRender><Form form={personEditForm} layout="vertical"><Form.Item name="name" label="姓名" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="phone" label="登录手机号" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="roles" label="职位角色"><Select mode="multiple" placeholder="选择职位角色" options={[{ value: 'academic_director', label: '教导主任' }, { value: 'head_teacher', label: '班主任' }, { value: 'subject_teacher', label: '任教老师' }]} /></Form.Item><Form.Item name="teacher_level" label="教师职级"><Select allowClear placeholder="非教师可留空" options={['特级教师', '正高级教师', '高级教师', '一级教师', '二级教师', '普通教师'].map((label) => ({ value: label, label }))} /></Form.Item></Form></Modal>
    <Modal title={editingUnit ? '编辑组织' : '新建组织'} open={unitOpen} onCancel={() => setUnitOpen(false)} onOk={() => void saveUnit()} confirmLoading={saving} okText="保存" forceRender><Form form={unitForm} layout="vertical"><Form.Item name="name" label="组织名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="unit_type" label="组织类型" rules={[{ required: true }]}><Select disabled={!!editingUnit} options={TYPE_OPTIONS} /></Form.Item><Form.Item name="parent_id" label="上级组织"><Select allowClear options={units.filter((item) => item.id !== editingUnit?.id).map((unit) => ({ label: unit.name, value: unit.id }))} /></Form.Item><div className="zh-form-grid"><Form.Item name="academic_year" label="所属学年"><Select allowClear placeholder="选择学年；长期组织留空" options={yearOptions} /></Form.Item><Form.Item name="cohort_label" label="对应届"><Input placeholder="例如：2029届" /></Form.Item></div><Form.Item noStyle shouldUpdate={(prev, next) => prev.unit_type !== next.unit_type}>{({ getFieldValue }) => getFieldValue('unit_type') === 'grade_group' ? <Form.Item name="grade_id" label="对应年级" rules={[{ required: true, message: '请选择对应年级' }]}><Select placeholder="选择高一年级 / 高二年级 / 高三年级" options={schoolGrades.map((grade) => ({ label: grade.name, value: grade.id }))} /></Form.Item> : null}</Form.Item></Form></Modal>
    <Modal title="师资调整建议" open={teacherAllocationOpen} onCancel={() => setTeacherAllocationOpen(false)} footer={[
      <Button key="cancel" onClick={() => setTeacherAllocationOpen(false)}>取消</Button>,
      !teacherPlanReady
        ? <Button key="preview" type="primary" onClick={() => void previewTeacherAllocation()}>生成调整建议</Button>
        : <Button key="apply" type="primary" loading={saving} disabled={staffingSummary.shortage > 0 || staffingSummary.headShortage > 0} onClick={() => modal.confirm({ title: '确认自动安排人员？', content: '系统将先校验所有学科教师和班主任数量，全部满足后才会一次性安排；任意一项不足都不会写入部分结果。', okText: '确认安排', cancelText: '取消', onOk: applyTeacherAllocation })}>自动安排人员</Button>,
    ]} width={760} centered destroyOnClose>
        <Form form={teacherAllocationForm} layout="vertical" onValuesChange={(changed) => { setTeacherPlanReady(false); if (changed.organization_unit_id) teacherAllocationForm.setFieldValue('class_count', getTargetGradeStats(changed.organization_unit_id).classCount || undefined); if (changed.allocation_mode === 'single') teacherAllocationForm.setFieldValue('teacher_id', undefined) }}>
        <Form.Item name="allocation_mode" label="编排方式"><Select options={[{ value: 'batch', label: '批量编排' }, { value: 'single', label: '单个分配' }]} /></Form.Item>
        <Form.Item name="source_unit_ids" label="教师来源（可多选同一学科）" rules={[{ required: true, message: '请选择教师来源学科组' }]}>
          <Select mode="multiple" showSearch optionFilterProp="label" placeholder="可多选教研组，教师仍按原学科任教" options={units.filter((item) => item.unit_type === 'subject_group' && item.status === 'active').map((item) => ({ value: item.id, label: item.name }))} />
        </Form.Item>
        {allocationMode === 'single' && <Form.Item name="teacher_id" label="指定教师" rules={[{ required: true, message: '请选择教师' }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择一名教师" options={accounts.filter((account) => account.status === 'active' && !account.is_school_admin && (!teacherPlanValues.source_unit_ids?.length || appointments.some((item) => item.staff_id === account.id && teacherPlanValues.source_unit_ids?.includes(item.organization_unit_id)))).map((account) => ({ value: account.id, label: account.name }))} />
        </Form.Item>}
        <Form.Item name="organization_unit_id" label="分配到年级部" rules={[{ required: true, message: '请选择年级部' }]}>
          <Select showSearch optionFilterProp="label" placeholder="选择年级管理中心下的年级部" notFoundContent="年级管理中心下暂无年级部,请先在组织机构中创建" options={gradeUnitOptions} />
        </Form.Item>
        <div className="zh-form-grid">
          <Form.Item name="class_count" label="目标班级数（自动读取）" rules={[{ required: true, message: '请先选择目标年级部' }]}><InputNumber min={1} max={200} disabled style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="max_classes_per_head_teacher" label="班主任最多带班数" rules={[{ required: true, message: '请输入班主任最多带班数' }]}><InputNumber min={1} max={20} style={{ width: '100%' }} placeholder="例如 2" /></Form.Item>
        </div>
        <div className="zh-form-grid">
          <Form.Item name="max_classes_per_teacher" label="非班主任最多带班数" rules={[{ required: true, message: '请输入非班主任最多带班数' }]}><InputNumber min={1} max={20} style={{ width: '100%' }} placeholder="例如 3" /></Form.Item>
          <Form.Item name="weekly_periods" label="每班每周课时" rules={[{ required: true, message: '请输入每班课时' }]}><InputNumber min={1} max={20} style={{ width: '100%' }} placeholder="例如 5" /></Form.Item>
          <Form.Item name="max_weekly_periods" label="教师每周课时上限" rules={[{ required: true, message: '请输入教师课时上限' }]}><InputNumber min={1} max={40} style={{ width: '100%' }} placeholder="例如 20" /></Form.Item>
        </div>
        <div className="zh-form-grid">
          <Form.Item name="position_code" label="任职岗位" rules={[{ required: true }]}><Select options={[{ value: 'member', label: '组织成员' }, { value: 'grade_director', label: '年级主任' }]} /></Form.Item>
          <Form.Item name="academic_year" label="任职学年"><Select allowClear placeholder="长期任职可留空" options={yearOptions} /></Form.Item>
        </div>
        {targetGradeStats.classCount > 0 && <div style={{ marginTop: 16 }}>
          <strong>各科初步师资测算</strong>
          <div style={{ marginTop: 8, border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr .8fr .8fr 1fr .8fr .8fr .8fr 1fr', gap: 8, padding: '10px 12px', background: 'var(--bg-2)', color: 'var(--text-2)', fontSize: 12 }}><span>学科</span><span>每班课时</span><span>班主任可用</span><span>总课时/周</span><span>当前</span><span>建议</span><span>全校可用</span><span>调整建议</span></div>
            {subjectStaffStats.map((row) => <div key={row.subject} style={{ display: 'grid', gridTemplateColumns: '1fr .8fr .8fr 1fr .8fr .8fr .8fr 1fr', gap: 8, padding: '9px 12px', borderTop: '1px solid var(--border)', fontSize: 13 }}><span>{row.subject}</span><span>{row.weeklyPeriods} 节</span><span title={`班主任 ${row.headTeachers} 人 × ${row.headCapacity} 班 = 覆盖 ${row.headCoverage} 班`}>{row.headTeachers} 人</span><span>{row.totalPeriods} 节</span><span>{row.sourceSelected ? `${row.current} 人` : '—'}</span><strong>{row.sourceSelected ? `${row.recommended} 人` : '—'}</strong><span>{row.sourceSelected ? `${row.available} 人` : '未选择'}</span><strong style={{ color: row.shortage ? '#b42318' : row.sourceSelected && row.adjustment !== 0 ? '#b26a00' : '#16845b' }}>{!row.sourceSelected ? '未选来源' : row.shortage ? `缺少 ${row.shortage}` : row.adjustment > 0 ? `建议补充 ${row.adjustment}` : row.adjustment < 0 ? `建议释放 ${-row.adjustment}` : '保持不变'}</strong></div>)}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr .8fr .8fr 1fr .8fr .8fr .8fr 1fr', gap: 8, padding: '10px 12px', borderTop: '1px solid var(--border)', background: '#f0f7ff', fontSize: 13 }}><strong>班主任配置</strong><span>—</span><strong>{headTeacherStats.required} 人</strong><span>{headTeacherStats.required} 个班</span><span>{headTeacherStats.current} 人</span><strong>{headTeacherStats.recommended} 人</strong><span>{headTeacherStats.sourceSelected ? `${headTeacherStats.available} 人` : '未选择'}</span><strong style={{ color: headTeacherStats.shortage ? '#b42318' : headTeacherStats.adjustment !== 0 ? '#b26a00' : '#16845b' }}>{!headTeacherStats.sourceSelected ? '未选来源' : headTeacherStats.shortage ? `缺少 ${headTeacherStats.shortage}` : headTeacherStats.fallbackRequired ? `其他学科补 ${headTeacherStats.fallbackRequired}` : headTeacherStats.adjustment > 0 ? `建议补充 ${headTeacherStats.adjustment}` : headTeacherStats.adjustment < 0 ? `建议释放 ${-headTeacherStats.adjustment}` : '保持不变'}</strong></div>
          </div>
          <div style={{ marginTop: 8, color: 'var(--text-3)', fontSize: 12 }}>计算方式：先统计所选学科组中未被其他年级占用、同时具备“任教老师”和“班主任”角色的教师；班主任按每人最多 {teacherPlanValues.max_classes_per_head_teacher || 2} 个班覆盖，剩余班级再按普通教师每人最多 {teacherPlanValues.max_classes_per_teacher || 3} 个班计算。总课时上限只用于校验教师工作量，不会把班主任按普通教师重复计算。</div>
        </div>}
        {teacherPlanReady && <div style={{ marginTop: 8, padding: 14, border: '1px solid var(--border)', borderRadius: 10, background: 'var(--bg-2)' }}>
          <strong style={{ color: staffingSummary.shortage || staffingSummary.headShortage ? '#b42318' : staffingSummary.add || staffingSummary.release || staffingSummary.headAdd || staffingSummary.headRelease ? '#b42318' : '#16845b' }}>
            {staffingSummary.shortage || staffingSummary.headShortage ? '无法安排' : staffingSummary.add || staffingSummary.release || staffingSummary.headAdd || staffingSummary.headRelease ? '需要调整' : '配置合理'}
          </strong>
          <div style={{ marginTop: 10, color: 'var(--text-2)', lineHeight: 1.8 }}>
            任课教师：当前 {staffingSummary.current} 人，建议 {staffingSummary.recommended} 人；班主任：当前 {staffingSummary.headCurrent} 人，目标 {staffingSummary.headRecommended} 人（{targetGradeStats.classCount} 个行政班）。当前年级 {targetGradeStats.studentCount} 名学生；任课教师建议补充 {staffingSummary.add} 人、释放 {staffingSummary.release} 人，班主任建议补充 {staffingSummary.headAdd} 人、释放 {staffingSummary.headRelease} 人{staffingSummary.shortage || staffingSummary.headShortage ? `；可用师资缺口 ${staffingSummary.shortage + staffingSummary.headShortage} 人` : ''}。
            <div>{staffingSummary.shortage || staffingSummary.headShortage ? '教师或班主任数量不足，不能自动安排；请补充对应学科组人员后再试。' : '确认后按建议安排人员，不会自动新增教师或调动其他年级教师。'}</div>
          </div>
        </div>}
      </Form>
    </Modal>
  </div>
}
