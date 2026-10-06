import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Input, Modal, Select, Space, Switch, Table, Tabs, Tag } from 'antd'
import type { TableProps } from 'antd'
import { authApi, gaokaoApi, orgApi, organizationApi, schedulingApi, staffApi } from '@/api'
import { allocateHeadTeachers, coreSubjectScore as getCoreSubjectScore } from './head-teacher-allocation'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import { GENDER_DICT } from '@/types/dict'
import type { AutoClassAssignmentResult, ClassInfo, Grade, OrganizationUnit, StaffAccount, StaffAppointment, Student, TeachingAssignment } from '@/types'

type ClassRule = {
  id: string
  name: string
  basis: 'stable' | 'snake' | 'subject_choice'
  genderBalance: boolean
  desc: string
  color: string
}

const getClassTypeLabel = (classType?: string) => {
  if (!classType || classType === 'regular' || classType === '普通班') return ''
  if (classType.includes('实验') || classType === 'experimental') return '实验班'
  if (classType.includes('重点') || classType === 'key') return '重点班'
  if (classType.includes('尖子') || classType === 'elite') return '尖子班'
  return classType
}

function ClassSubjectTag({ track }: { track: ClassInfo['subject_track'] }) {
  const label = track === 'physics' ? '物理班' : track === 'history' ? '历史班' : track === 'mixed' ? '选科混合' : '待确定选科'
  const color = track === 'physics' ? 'blue' : track === 'history' ? 'orange' : track === 'mixed' ? 'red' : undefined
  return <Tag color={color} style={{ margin: 0 }}>{label}</Tag>
}

const CLASS_RULES_KEY = 'light-classroom-class-assignment-rules'
const WALK_CLASS_RULE: ClassRule = {
  id: 'walk-class',
  name: '走班分班',
  basis: 'subject_choice',
  genderBalance: false,
  desc: '按物理/历史首选科目隔离班级池，并在各自池内均衡分班',
  color: '#0f766e',
}
const DEFAULT_CLASS_RULES: ClassRule[] = [
  { id: 'stable', name: '学号顺序分班', basis: 'stable', genderBalance: false, desc: '按学号顺序依次分入已分配教室的行政班', color: '#64748b' },
  { id: 'snake', name: '名册蛇形分班', basis: 'snake', genderBalance: true, desc: '按名册顺序往返分配，适合没有统一成绩的场景', color: '#7c3aed' },
  WALK_CLASS_RULE,
]

export default function ClassesView() {
  const { message } = App.useApp()
  const [grades, setGrades] = useState<Grade[]>([])
  const [classes, setClasses] = useState<ClassInfo[]>([])
  const [students, setStudents] = useState<Student[]>([])
  const [primarySubjectByStudent, setPrimarySubjectByStudent] = useState<Map<number, string>>(new Map())
  const [staff, setStaff] = useState<StaffAccount[]>([])
  const [appointments, setAppointments] = useState<StaffAppointment[]>([])
  const [organizationUnits, setOrganizationUnits] = useState<OrganizationUnit[]>([])
  const [teachingAssignments, setTeachingAssignments] = useState<TeachingAssignment[]>([])
  const [gradeId, setGradeId] = useState<number>()
  const [selectedClassId, setSelectedClassId] = useState<number>()
  const [classKeyword, setClassKeyword] = useState('')
  const [rosterKeyword, setRosterKeyword] = useState('')
  const [rosterGender, setRosterGender] = useState<'male' | 'female' | ''>('')
  const [rosterPage, setRosterPage] = useState(1)
  const [rosterPageSize, setRosterPageSize] = useState(10)
  const [candidateKeyword, setCandidateKeyword] = useState('')
  const [candidatePage, setCandidatePage] = useState(1)
  const [candidatePageSize, setCandidatePageSize] = useState(10)
  const [selectedStudentIds, setSelectedStudentIds] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [assigning, setAssigning] = useState(false)
  const [assignDialog, setAssignDialog] = useState(false)
  const [activeTab, setActiveTab] = useState('rules')
  const [autoPreview, setAutoPreview] = useState<AutoClassAssignmentResult>()
  const [autoLoading, setAutoLoading] = useState(false)
  const [autoAssignDialog, setAutoAssignDialog] = useState(false)
  const [rules, setRules] = useState<ClassRule[]>(() => {
    try {
      const saved = localStorage.getItem(CLASS_RULES_KEY)
      if (!saved) return DEFAULT_CLASS_RULES
      const parsed = JSON.parse(saved) as ClassRule[]
      const compatible = parsed.filter((item) => item.basis !== ('score_balanced' as string))
      return compatible.some((item) => item.id === WALK_CLASS_RULE.id) ? compatible : [...compatible, WALK_CLASS_RULE]
    } catch {
      return DEFAULT_CLASS_RULES
    }
  })
  const [defaultRuleId, setDefaultRuleId] = useState(() => localStorage.getItem(`${CLASS_RULES_KEY}-default`) || 'stable')
  const [selectedRuleId, setSelectedRuleId] = useState(() => localStorage.getItem(`${CLASS_RULES_KEY}-default`) || 'stable')
  const [ruleModalOpen, setRuleModalOpen] = useState(false)
  const [editingRuleId, setEditingRuleId] = useState<string>()
  const [ruleName, setRuleName] = useState('')
  const [ruleBasis, setRuleBasis] = useState<ClassRule['basis']>('stable')
  const [ruleGenderBalance, setRuleGenderBalance] = useState(true)
  const [ruleDesc, setRuleDesc] = useState('')
  const [headTeacherDialog, setHeadTeacherDialog] = useState(false)
  const [headTeacherId, setHeadTeacherId] = useState<number>()
  const [headTeacherSaving, setHeadTeacherSaving] = useState(false)
  const [batchHeadTeacherDialog, setBatchHeadTeacherDialog] = useState(false)
  const [batchHeadTeacherMap, setBatchHeadTeacherMap] = useState<Record<number, number>>({})
  const [batchHeadTeacherSaving, setBatchHeadTeacherSaving] = useState(false)
  const [batchHeadTeacherPage, setBatchHeadTeacherPage] = useState(1)
  const [batchHeadTeacherPageSize, setBatchHeadTeacherPageSize] = useState(10)
  const [academicYear, setAcademicYear] = useState(() => {
    const year = new Date().getMonth() >= 7 ? new Date().getFullYear() : new Date().getFullYear() - 1
    return `${year}-${year + 1}`
  })
  const [term, setTerm] = useState(() => new Date().getMonth() >= 1 && new Date().getMonth() < 7 ? '2' : '1')

  const selectedClass = useMemo(
    () => classes.find((item) => item.id === selectedClassId),
    [classes, selectedClassId],
  )
  const classStudents = useMemo(
    () => students.filter((item) => item.class_id === selectedClassId),
    [students, selectedClassId],
  )
  const filteredClasses = useMemo(() => {
    const query = classKeyword.trim().toLowerCase()
    return query ? classes.filter((item) => item.name.toLowerCase().includes(query)) : classes
  }, [classes, classKeyword])
  const filteredClassStudents = useMemo(() => {
    const query = rosterKeyword.trim().toLowerCase()
    return classStudents.filter((item) => {
      const matchesKeyword =
        !query ||
        item.name.toLowerCase().includes(query) ||
        (item.student_no ?? '').toLowerCase().includes(query)
      const matchesGender = !rosterGender || item.gender === rosterGender
      return matchesKeyword && matchesGender
    })
  }, [classStudents, rosterKeyword, rosterGender])
  const pagedClassStudents = useMemo(
    () =>
      filteredClassStudents.slice(
        (rosterPage - 1) * rosterPageSize,
        rosterPage * rosterPageSize,
      ),
    [filteredClassStudents, rosterPage, rosterPageSize],
  )
  const assignmentCandidates = useMemo(() => {
    const query = candidateKeyword.trim().toLowerCase()
    return students.filter(
      (item) =>
        item.class_id !== selectedClassId &&
        (!query ||
          item.name.toLowerCase().includes(query) ||
          (item.student_no ?? '').toLowerCase().includes(query)),
    )
  }, [students, selectedClassId, candidateKeyword])
  const pagedCandidates = useMemo(
    () =>
      assignmentCandidates.slice(
        (candidatePage - 1) * candidatePageSize,
        candidatePage * candidatePageSize,
      ),
    [assignmentCandidates, candidatePage, candidatePageSize],
  )
  const unassignedCount = useMemo(
    () => students.filter((item) => !item.class_id).length,
    [students],
  )
  const assignableClasses = useMemo(() => classes.filter((item) => item.home_room_id && item.resource_assigned !== false), [classes])
  const selectedRule = rules.find((rule) => rule.id === selectedRuleId) ?? rules[0]
  const gradeGroupUnitIds = useMemo(() => {
    const result = new Set<number>()
    const visit = (units: OrganizationUnit[]) => {
      units.forEach((unit) => {
        if (unit.unit_type === 'grade_group' && unit.grade_id === gradeId) result.add(unit.id)
        if (unit.children?.length) visit(unit.children)
      })
    }
    visit(organizationUnits)
    return result
  }, [gradeId, organizationUnits])
  const gradeName = grades.find((item) => item.id === gradeId)?.name ?? ''
  const gradeScopedAppointments = useMemo(() => appointments.filter((item) => {
    if (item.status !== 'active') return false
    if (item.academic_year && item.academic_year !== academicYear) return false
    return gradeGroupUnitIds.has(item.organization_unit_id)
      || (!gradeGroupUnitIds.size && gradeName && item.organization_name.includes(gradeName))
  }), [academicYear, appointments, gradeGroupUnitIds, gradeName])
  const headTeacherCandidates = useMemo(() => {
    // 候选=已挂载到当前年级部、具备任课老师角色的在职教师。
    // 班主任可以先安排，任教关系稍后生成，因此不能用 TeachingAssignment 反向限制候选。
    const gradeStaffIds = new Set(gradeScopedAppointments.map((item) => item.staff_id))
    const coreSubjectScore = (staffId: number) => {
      const names = gradeScopedAppointments
        .filter((item) => item.staff_id === staffId && item.status === 'active')
        .map((item) => item.organization_name)
      if (names.some((name) => name.includes('语文'))) return 0
      if (names.some((name) => name.includes('数学'))) return 1
      if (names.some((name) => name.includes('英语'))) return 2
      return 3
    }
    return staff.filter((item) => gradeStaffIds.has(item.id) && item.status === 'active'
      && item.roles.includes('subject_teacher')
      && !gradeScopedAppointments.some((appointment) => appointment.staff_id === item.id && appointment.organization_name.includes('体育')))
      .sort((left, right) => coreSubjectScore(left.id) - coreSubjectScore(right.id) || left.id - right.id)
  }, [gradeScopedAppointments, staff])
  const teachingAssignmentsByClass = useMemo(() => {
    const result = new Map<number, TeachingAssignment[]>()
    teachingAssignments
      .filter((item) => item.academic_year === academicYear && item.term === term)
      .forEach((item) => {
        const current = result.get(item.class_id) ?? []
        current.push(item)
        result.set(item.class_id, current)
      })
    return result
  }, [academicYear, teachingAssignments, term])
  const classHeadTeacherCandidates = useCallback((classId: number) => {
    const subjectPriority = (name?: string) => {
      if (name?.includes('语文')) return 0
      if (name?.includes('数学')) return 1
      if (name?.includes('英语')) return 2
      return 3
    }
    const teachers = new Map(headTeacherCandidates.map((item) => [item.id, item]))
    const assignedCandidates = (teachingAssignmentsByClass.get(classId) ?? [])
      .filter((assignment) => assignment.teacher_id !== null && teachers.has(assignment.teacher_id))
      .map((assignment) => ({
        teacher: teachers.get(assignment.teacher_id!)!,
        subjectName: assignment.subject_name,
      }))
      .sort((left, right) => subjectPriority(left.subjectName) - subjectPriority(right.subjectName) || left.teacher.id - right.teacher.id)
      .map((item) => item.teacher)
    const assignedIds = new Set(assignedCandidates.map((item) => item.id))
    return [...assignedCandidates, ...headTeacherCandidates.filter((item) => !assignedIds.has(item.id))]
  }, [headTeacherCandidates, teachingAssignmentsByClass])

  const persistRules = (next: ClassRule[]) => {
    setRules(next)
    localStorage.setItem(CLASS_RULES_KEY, JSON.stringify(next))
  }

  useEffect(() => {
    setRosterPage(1)
  }, [selectedClassId, rosterKeyword, rosterGender])

  const resetRosterFilters = () => {
    setRosterKeyword('')
    setRosterGender('')
  }

  const loadData = async () => {
    setLoading(true)
    try {
      const academicSettings = await authApi.academicYears()
      const scopedAcademicYear = academicSettings.current_academic_year || academicYear
      const scopedTerm = academicSettings.current_term || term
      setAcademicYear(scopedAcademicYear)
      setTerm(scopedTerm)
      const gradeList = await orgApi.grades()
      setGrades(gradeList)
      const gid = gradeId ?? gradeList[0]?.id
      if (gid !== undefined && gradeId === undefined) setGradeId(gid)
      const [classList, studentList, staffDirectory, appointmentList, schedulingResources, organizationTree, choices] = await Promise.all([
        orgApi.classes(gid !== undefined ? { grade_id: gid, academic_year: scopedAcademicYear, term: scopedTerm } : { academic_year: scopedAcademicYear, term: scopedTerm }),
        orgApi.students(undefined, undefined, gid, { academic_year: scopedAcademicYear, term: scopedTerm }),
        staffApi.list().catch(() => ({ accounts: [], roles: [] })),
        organizationApi.appointments().catch(() => []),
        schedulingApi.resources().catch(() => ({ teachers: [], subjects: [], classes: [], assignments: [] })),
        organizationApi.tree().catch(() => ({ school: { id: 0, name: '' }, units: [] })),
        gaokaoApi.choicesForReview({ academic_year: scopedAcademicYear, term: scopedTerm, status_filter: '' }).catch(() => []),
      ])
      setClasses(classList)
      setStudents(studentList)
      setPrimarySubjectByStudent(new Map(
        choices
          .filter((choice) => choice.status === 'confirmed' || choice.status === 'locked')
          .map((choice) => [choice.student_id, choice.primary_subject_name]),
      ))
      setStaff(staffDirectory.accounts)
      setAppointments(appointmentList)
      setOrganizationUnits(organizationTree.units)
      setTeachingAssignments(schedulingResources.assignments)
      if (!classList.some((item) => item.id === selectedClassId)) {
        setSelectedClassId(classList[0]?.id)
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '班级数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  const openHeadTeacherDialog = () => {
    if (!selectedClass) {
      message.warning('请先选择一个行政班')
      return
    }
    setHeadTeacherId(selectedClass.head_teacher_id)
    setHeadTeacherDialog(true)
  }

  const saveHeadTeacher = async () => {
    if (!selectedClass || !headTeacherId) {
      message.warning('请选择班主任')
      return
    }
    setHeadTeacherSaving(true)
    try {
      const updated = await orgApi.assignHeadTeacher(selectedClass.id, {
        teacher_id: headTeacherId,
        academic_year: academicYear,
        term,
      })
      setClasses((prev) => prev.map((item) => item.id === updated.id ? { ...item, ...updated } : item))
      setHeadTeacherDialog(false)
      message.success(`已为${selectedClass.name}安排班主任`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '班主任安排失败')
    } finally {
      setHeadTeacherSaving(false)
    }
  }

  const openBatchHeadTeacherDialog = async () => {
    if (!filteredClasses.length) {
      message.warning('当前年级暂无行政班')
      return
    }
    // 先打开方案窗口，避免等待配置接口时按钮看起来无响应
    setBatchHeadTeacherDialog(true)
    setBatchHeadTeacherPage(1)
    const nextMap: Record<number, number> = Object.fromEntries(
      filteredClasses
        .filter((item) => item.head_teacher_id)
        .map((item) => [item.id, item.head_teacher_id!]),
    )
    const currentLoad = new Map<number, number>()
    Object.values(nextMap).forEach((teacherId) => currentLoad.set(teacherId, (currentLoad.get(teacherId) || 0) + 1))
    const pendingClasses = filteredClasses.filter((item) => !item.head_teacher_id)
    if (!pendingClasses.length) {
      setBatchHeadTeacherMap(nextMap)
      return
    }
    // 先按主科优先汇总候选，再轮换分配；班主任不设置固定带班数上限。
    const budgetCandidates = pendingClasses.flatMap((item) => {
      const assignments = teachingAssignmentsByClass.get(item.id) ?? []
      return classHeadTeacherCandidates(item.id).map((teacher) => ({
        id: teacher.id,
        subject: assignments.find((assignment) => assignment.teacher_id === teacher.id)?.subject_name || '其他',
      }))
    })
    // 去重(同一教师跨班候选只算一次),学科取其主科归属
    const uniqueCandidates = Array.from(new Map(budgetCandidates.map((c) => [c.id, c])).values())
    const orderedCandidates = uniqueCandidates
      .sort((left, right) => getCoreSubjectScore([left.subject]) - getCoreSubjectScore([right.subject]) || left.id - right.id)
      .map((item) => ({ id: item.id }))
    const allocation = allocateHeadTeachers(pendingClasses.map((item) => item.id), orderedCandidates, nextMap)
    Object.assign(nextMap, allocation.assignments)
    setBatchHeadTeacherMap(nextMap)
    if (allocation.unfilledCount) {
      message.warning(`当前可用班主任不足,仍有 ${allocation.unfilledCount} 个班级待安排`)
    }
  }

  const saveBatchHeadTeachers = async () => {
    const entries = Object.entries(batchHeadTeacherMap)
      .filter(([classId, teacherId]) => teacherId && classes.find((item) => item.id === Number(classId))?.head_teacher_id !== Number(teacherId))
    if (!entries.length) {
      if (filteredClasses.length && filteredClasses.every((item) => item.head_teacher_id)) {
        setBatchHeadTeacherDialog(false)
        message.info('当前年级的班主任已全部安排')
      } else {
        message.warning('请至少为一个班级选择班主任')
      }
      return
    }
    setBatchHeadTeacherSaving(true)
    let successCount = 0
    try {
      for (const [classId, teacherId] of entries) {
        const updated = await orgApi.assignHeadTeacher(Number(classId), {
          teacher_id: Number(teacherId),
          academic_year: academicYear,
          term,
        })
        setClasses((prev) => prev.map((item) => item.id === updated.id ? { ...item, ...updated } : item))
        successCount += 1
      }
      setBatchHeadTeacherDialog(false)
      message.success(`已完成 ${successCount} 个班级的班主任安排`)
    } catch (error) {
      message.error(`${error instanceof Error ? error.message : '批量安排失败'}，已完成 ${successCount} 个班级`)
    } finally {
      setBatchHeadTeacherSaving(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  const openAssignment = () => {
    setSelectedStudentIds([])
    setCandidateKeyword('')
    setCandidatePage(1)
    setAssignDialog(true)
  }

  const assignStudents = async () => {
    if (!selectedClassId || !selectedStudentIds.length) {
      message.warning('请选择需要分配的学生')
      return
    }
    setAssigning(true)
    try {
      await orgApi.assignStudents(selectedStudentIds, selectedClassId, {
        academic_year: academicYear, term, grade_id: selectedClass?.grade_id,
        cohort_label: selectedClass?.cohort_label || undefined,
      })
      setAssignDialog(false)
      message.success(`已将 ${selectedStudentIds.length} 名学生分入${selectedClass?.name}`)
      await loadData()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '分班失败')
    } finally {
      setAssigning(false)
    }
  }

  const removeFromClass = async (student: Student) => {
    try {
      await orgApi.assignStudents([student.id], null, {
        academic_year: academicYear, term, grade_id: selectedClass?.grade_id,
        cohort_label: selectedClass?.cohort_label || undefined,
      })
      message.success(`${student.name}已移回待分班名单`)
      await loadData()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const autoAssignPayload = () => ({
    grade_id: gradeId!,
    class_ids: assignableClasses.map((item) => item.id),
    strategy: selectedRule?.basis ?? 'stable',
    balance_gender: selectedRule?.genderBalance ?? true,
    overwrite_existing: false,
  })

  const openNewRule = () => {
    setEditingRuleId(undefined)
    setRuleName('')
    setRuleBasis('stable')
    setRuleGenderBalance(true)
    setRuleDesc('')
    setRuleModalOpen(true)
  }

  const openEditRule = (rule: ClassRule) => {
    setEditingRuleId(rule.id)
    setRuleName(rule.name)
    setRuleBasis(rule.basis)
    setRuleGenderBalance(rule.genderBalance)
    setRuleDesc(rule.desc)
    setRuleModalOpen(true)
  }

  const saveRule = () => {
    const name = ruleName.trim()
    if (!name) { message.warning('请输入规则名称'); return }
    const nextRule: ClassRule = {
      id: editingRuleId ?? `custom-${Date.now()}`,
      name,
      basis: ruleBasis,
      genderBalance: ruleGenderBalance,
      desc: ruleDesc.trim() || (ruleBasis === 'stable' ? '按学号顺序分班' : ruleBasis === 'subject_choice' ? '按学生选课组合分班' : '按名册蛇形分班'),
      color: editingRuleId ? (rules.find((item) => item.id === editingRuleId)?.color ?? '#64748b') : '#0f766e',
    }
    const next = editingRuleId ? rules.map((item) => item.id === editingRuleId ? nextRule : item) : [...rules, nextRule]
    persistRules(next)
    setSelectedRuleId(nextRule.id)
    setRuleModalOpen(false)
    message.success(editingRuleId ? '规则已更新' : '规则已创建')
  }

  const setDefaultRule = (id: string) => {
    setDefaultRuleId(id)
    setSelectedRuleId(id)
    localStorage.setItem(`${CLASS_RULES_KEY}-default`, id)
    message.success('已设为默认规则')
  }

  const removeRule = (id: string) => {
    if (rules.length <= 1) { message.warning('至少保留一条分班规则'); return }
    const next = rules.filter((item) => item.id !== id)
    persistRules(next)
    if (selectedRuleId === id) setSelectedRuleId(next[0].id)
    if (defaultRuleId === id) setDefaultRule(next[0].id)
    message.success('规则已删除')
  }

  const previewAutoAssignment = async () => {
    if (!gradeId || !assignableClasses.length) { message.warning('请先选择有教室的行政班'); return }
    setAutoLoading(true)
    try {
      const result = await orgApi.autoAssignPreview(autoAssignPayload())
      setAutoPreview(result)
      setActiveTab('classes')
      setAutoAssignDialog(true)
      message.success(`已生成预览，共 ${result.total_students} 名待分班学生`)
    } catch (error) { message.error(error instanceof Error ? error.message : '自动分班预览失败') }
    finally { setAutoLoading(false) }
  }

  const executeAutoAssignment = async () => {
    if (!autoPreview) { message.warning('请先生成分班预览'); return }
    setAutoLoading(true)
    try {
      const result = await orgApi.autoAssign(autoAssignPayload())
      setAutoPreview(result)
      message.success(`已完成自动分班，共分配 ${result.assignments.length} 人`)
      await loadData()
      setAutoAssignDialog(false)
    } catch (error) { message.error(error instanceof Error ? error.message : '自动分班执行失败') }
    finally { setAutoLoading(false) }
  }

  const printAssignmentSheet = () => {
    if (!autoPreview) { message.warning('请先生成或执行分班预览'); return }
    window.print()
  }

  const rosterColumns: TableProps<Student>['columns'] = [
    { title: '学号', dataIndex: 'student_no', width: 160, render: (value: string) => value || '—' },
    { title: '姓名', dataIndex: 'name', width: 120 },
    { title: '首选科目（+1）', key: 'primary_subject', width: 150, render: (_, record) => primarySubjectByStudent.get(record.id) || '—' },
    {
      title: '性别',
      dataIndex: 'gender',
      width: 90,
      render: (value: string) => <DictTag dict={GENDER_DICT} value={value} />,
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      align: 'right',
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => removeFromClass(record)}>
          移出班级
        </Button>
      ),
    },
  ]

  const candidateColumns: TableProps<Student>['columns'] = [
    { title: '学号', dataIndex: 'student_no', width: 140, render: (value: string) => value || '—' },
    { title: '姓名', dataIndex: 'name', width: 110 },
    {
      title: '当前班级',
      key: 'class',
      width: 140,
      render: (_, record) => record.class_name || '待分班',
    },
  ]

  return (
    <div className="zh-page">
      <PageHeader title="行政班管理" extra={activeTab === 'rules' ? <Button type="primary" icon={<Icon name="plus" size={14} />} onClick={openNewRule}>新建规则</Button> : undefined} />
      <p className="zh-page-desc">
        行政班由“空间资源 → 班级划分”根据已分配教室生成；本页面负责学生分班、班级名单和日常管理。
      </p>

      <Tabs className="zh-class-tabs" activeKey={activeTab} onChange={setActiveTab}>
        <Tabs.TabPane tab="规则设定" key="rules">
          <TableCard>
            <Table<ClassRule>
              rowKey="id"
              dataSource={rules}
              pagination={{ pageSize: 8, showSizeChanger: false, showTotal: (total) => `共 ${total} 条规则` }}
              columns={[
                { title: '规则名称', dataIndex: 'name', width: 230, render: (name: string, record) => <span className="st-rule-name"><i style={{ color: record.color, background: `${record.color}1a` }}><Icon name="clipboard" size={16} /></i><span className="st-rule-name-text">{name}{defaultRuleId === record.id && <Tag className="st-rule-default">默认</Tag>}</span></span> },
                { title: '分班依据', dataIndex: 'basis', width: 150, render: (value: ClassRule['basis']) => <Tag color="blue">{{ stable: '学号顺序', snake: '名册蛇形', subject_choice: '选课组合' }[value]}</Tag> },
                { title: '均衡方式', dataIndex: 'genderBalance', width: 130, render: (value: boolean) => value ? <Tag color="green">性别均衡</Tag> : <span>不启用</span> },
                { title: '说明', dataIndex: 'desc', ellipsis: true },
                { title: '启用', key: 'enabled', width: 90, render: (_, record) => <Switch size="small" checked={defaultRuleId === record.id} checkedChildren="开" unCheckedChildren="关" onChange={(checked) => { if (checked) setDefaultRule(record.id) }} /> },
                { title: '操作', key: 'action', width: 110, align: 'right', render: (_, record) => <Space><Button type="text" size="small" title="编辑" icon={<Icon name="edit" size={14} />} onClick={() => openEditRule(record)} /><Button type="text" size="small" danger title="删除" icon={<Icon name="trash" size={14} />} onClick={() => removeRule(record.id)} /></Space> },
              ]}
            />
          </TableCard>
        </Tabs.TabPane>
        <Tabs.TabPane tab="班级名单" key="classes">
      <div className="zh-class-workspace">
        <aside className="zh-class-list">
          <div className="zh-class-filter">
            <label className="zh-filter-field">
              <span>年级</span>
              <Select
                value={gradeId}
                onChange={(v) => {
                  setGradeId(v)
                  void loadData()
                }}
                placeholder="选择年级"
                style={{ width: '100%' }}
                options={grades.map((g) => ({ label: g.name, value: g.id }))}
              />
            </label>
            <label className="zh-filter-field">
              <span>班级</span>
              <Input
                value={classKeyword}
                onChange={(e) => setClassKeyword(e.target.value)}
                allowClear
                placeholder="搜索班级名称"
              />
            </label>
            <div className="zh-class-search-head-teacher">
              班主任：{selectedClass?.head_teacher_name || '未安排'}
            </div>
            <Space className="zh-class-filter-footer">
              <small>待分班 {unassignedCount} 人</small>
              <Button
                htmlType="button"
                onClick={() => {
                  setBatchHeadTeacherDialog(true)
                  void openBatchHeadTeacherDialog()
                }}
              >
                一键安排班主任
              </Button>
            </Space>
          </div>
          <div className="zh-class-list-scroll">
            {filteredClasses.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`zh-class-row${item.id === selectedClassId ? ' active' : ''}`}
                onClick={() => setSelectedClassId(item.id)}
              >
                <span>
                  <strong className="zh-class-title">
                    {item.name}
                    {getClassTypeLabel(item.class_type) && (
                      <em className="zh-class-hot-badge" title={getClassTypeLabel(item.class_type)}>
                        {getClassTypeLabel(item.class_type).slice(0, 1)}
                      </em>
                    )}
                  </strong>
                  <small><ClassSubjectTag track={item.subject_track} /></small>
                  <small className={item.head_teacher_name ? undefined : 'pending-text'}>
                    {item.head_teacher_name ? `班主任：${item.head_teacher_name}` : '未安排班主任'}
                  </small>
                </span>
                <b>{item.student_count || 0} 人</b>
              </button>
            ))}
            {!filteredClasses.length && (
              <div className="zh-empty-class">没有符合条件的班级</div>
            )}
          </div>
        </aside>

        <main className="zh-roster">
          <div className="zh-roster-header">
            <div>
              <h2>{selectedClass?.name || '请选择班级'}{selectedClass && <span style={{ marginLeft: 10 }}><ClassSubjectTag track={selectedClass.subject_track} /></span>}</h2>
              <span>{classStudents.length} 名学生 · 当前规则：{selectedRule?.name || '未设置'}</span>
            </div>
            <Space>
              <Select size="small" value={selectedRule?.id} onChange={(value) => { setSelectedRuleId(value); setAutoPreview(undefined) }} options={rules.map((rule) => ({ label: rule.name, value: rule.id }))} style={{ width: 180 }} />
              <Button onClick={openHeadTeacherDialog} disabled={!selectedClassId}>
                {selectedClass?.head_teacher_name ? '更换班主任' : '安排班主任'}
              </Button>
              <Button type="primary" loading={autoLoading} onClick={previewAutoAssignment}>自动分班</Button>
              <Button disabled={!selectedClassId} onClick={openAssignment}>手动分配</Button>
            </Space>
          </div>
          <div className="zh-roster-toolbar">
            <label className="zh-filter-field">
              <span>学生</span>
              <Input
                value={rosterKeyword}
                onChange={(e) => setRosterKeyword(e.target.value)}
                allowClear
                placeholder="姓名或学号"
                style={{ width: 200 }}
              />
            </label>
            <label className="zh-filter-field">
              <span>性别</span>
              <Select
                value={rosterGender || undefined}
                onChange={(v) => setRosterGender((v ?? '') as 'male' | 'female' | '')}
                allowClear
                placeholder="全部性别"
                style={{ width: 140 }}
                options={[
                  { label: '男', value: 'male' },
                  { label: '女', value: 'female' },
                ]}
              />
            </label>
            <Button onClick={resetRosterFilters}>重置</Button>
          </div>
          <Table<Student>
            rowKey="id"
            columns={rosterColumns}
            dataSource={pagedClassStudents}
            loading={loading}
            pagination={{
              current: rosterPage,
              pageSize: rosterPageSize,
              total: filteredClassStudents.length,
              onChange: (p, s) => {
                setRosterPage(p)
                setRosterPageSize(s)
              },
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 条`,
            }}
            locale={{
              emptyText: (
                <EmptyState height={220} title="该班暂无符合条件的学生" desc="可通过“手动分配”加入成员" />
              ),
            }}
          />
        </main>
      </div>
        </Tabs.TabPane>
      </Tabs>

      <Modal
        title={editingRuleId ? '编辑分班规则' : '新建分班规则'}
        open={ruleModalOpen}
        onOk={saveRule}
        onCancel={() => setRuleModalOpen(false)}
        okText={editingRuleId ? '保存' : '创建'}
        cancelText="取消"
        width={460}
      >
        <div className="st-modal-form">
          <label className="zh-filter-field"><span>规则名称</span><Input value={ruleName} onChange={(e) => setRuleName(e.target.value)} placeholder="例如：中考成绩均衡分班" maxLength={30} /></label>
          <label className="zh-filter-field"><span>分班依据</span><Select value={ruleBasis} onChange={setRuleBasis} options={[{ label: '按选课组合分班', value: 'subject_choice' }, { label: '学号顺序', value: 'stable' }, { label: '名册蛇形', value: 'snake' }]} /></label>
          <label className="zh-filter-field"><span>性别均衡</span><Switch checked={ruleGenderBalance} onChange={setRuleGenderBalance} checkedChildren="开启" unCheckedChildren="关闭" /></label>
          <label className="zh-filter-field"><span>规则说明</span><Input.TextArea value={ruleDesc} onChange={(e) => setRuleDesc(e.target.value)} rows={3} maxLength={100} placeholder="说明该规则适用的分班场景" /></label>
        </div>
      </Modal>

      <Modal
        title="一键安排班主任"
        open={batchHeadTeacherDialog}
        onCancel={() => setBatchHeadTeacherDialog(false)}
        onOk={saveBatchHeadTeachers}
        okText="确认一键安排"
        cancelText="取消"
        confirmLoading={batchHeadTeacherSaving}
        width={720}
      >
        <p className="zh-page-desc">仅从已任教本班的教师中安排；语文、数学、英语优先。确认时会为入选教师补充班主任角色，已安排的班主任保持不变；同一教师可担任多个班的班主任。</p>
        <Table
          rowKey="id"
          size="small"
          pagination={{
            current: batchHeadTeacherPage,
            pageSize: batchHeadTeacherPageSize,
            total: filteredClasses.length,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 30],
            showTotal: (total) => `共 ${total} 个班级`,
            onChange: (page, pageSize) => {
              setBatchHeadTeacherPage(page)
              setBatchHeadTeacherPageSize(pageSize)
            },
          }}
          dataSource={filteredClasses}
          columns={[
            { title: '行政班', dataIndex: 'name' },
            { title: '学生', dataIndex: 'student_count', render: (value: number) => `${value || 0} 人` },
            {
              title: '班主任',
              key: 'head_teacher',
              render: (_: unknown, record: ClassInfo) => (
                <Select
                  value={batchHeadTeacherMap[record.id]}
                  onChange={(value) => setBatchHeadTeacherMap((prev) => ({ ...prev, [record.id]: value }))}
                  showSearch
                  optionFilterProp="label"
                  placeholder="请选择"
                  style={{ width: 260 }}
                  options={classHeadTeacherCandidates(record.id).map((item) => ({ label: item.name, value: item.id }))}
                />
              ),
            },
          ]}
        />
      </Modal>

      <Modal
        title={`${selectedClass?.name || ''} · 安排班主任`}
        open={headTeacherDialog}
        onCancel={() => setHeadTeacherDialog(false)}
        onOk={saveHeadTeacher}
        okText="保存安排"
        cancelText="取消"
        confirmLoading={headTeacherSaving}
        width={480}
      >
        <div className="zh-form-grid">
          <label className="zh-filter-field">
            <span>学年</span>
            <Input value={academicYear} onChange={(event) => setAcademicYear(event.target.value)} placeholder="如 2026-2027" />
          </label>
          <label className="zh-filter-field">
            <span>学期</span>
            <Select value={term} onChange={setTerm} options={[{ label: '第 1 学期', value: '1' }, { label: '第 2 学期', value: '2' }]} />
          </label>
        </div>
        <label className="zh-filter-field">
          <span>班主任</span>
          <Select
            value={headTeacherId}
            onChange={setHeadTeacherId}
            showSearch
            optionFilterProp="label"
            placeholder="选择符合条件的教师"
            style={{ width: '100%' }}
            options={selectedClass ? classHeadTeacherCandidates(selectedClass.id).map((item) => ({ label: `${item.name}（${item.phone}）`, value: item.id })) : []}
            notFoundContent="暂无符合条件的教师"
          />
        </label>
        <p className="zh-page-desc">系统会校验教师状态、角色，以及当前学期是否任教本班课程。</p>
      </Modal>

      <Modal title="自动分班预览" open={autoAssignDialog} onCancel={() => setAutoAssignDialog(false)} width={920} centered destroyOnHidden footer={<Space><Button onClick={() => setAutoAssignDialog(false)}>取消</Button><Button onClick={printAssignmentSheet} disabled={!autoPreview}>打印分班表</Button><Button type="primary" loading={autoLoading} disabled={!autoPreview} onClick={executeAutoAssignment}>确认分班</Button></Space>}>
        {!autoPreview ? <EmptyState height={220} title="正在生成分班预览" desc="请稍候" /> : <><div className="zh-auto-assignment-summary"><strong>已分班 {autoPreview.assigned_student_count ?? 0} 人</strong><span>待分班 {autoPreview.total_students} 人</span><span>本次启用 {autoPreview.required_class_count ?? autoPreview.classes.length} 个班</span><span>备用 {autoPreview.unused_class_count ?? 0} 个班</span><span>预计未分班 {autoPreview.unassigned_count} 人</span></div><Table rowKey="id" size="small" dataSource={autoPreview.classes} pagination={false} columns={[{ title: '行政班', dataIndex: 'name' }, { title: '人数', dataIndex: 'student_count' }, { title: '容量', dataIndex: 'capacity' }, { title: '男生', dataIndex: 'male_count' }, { title: '女生', dataIndex: 'female_count' }]} /></>}
      </Modal>

      <Modal
        title={`手动分配到${selectedClass?.name || '班级'}`}
        open={assignDialog}
        onCancel={() => setAssignDialog(false)}
        onOk={assignStudents}
        okText="确认分配"
        cancelText="取消"
        confirmLoading={assigning}
        width={620}
      >
        <Input
          value={candidateKeyword}
          onChange={(e) => {
            setCandidateKeyword(e.target.value)
            setCandidatePage(1)
          }}
          allowClear
          placeholder="搜索姓名或学号"
          style={{ marginBottom: 10 }}
        />
        <Table<Student>
          rowKey="id"
          columns={candidateColumns}
          dataSource={pagedCandidates}
          rowSelection={{
            preserveSelectedRowKeys: true,
            selectedRowKeys: selectedStudentIds,
            onChange: (keys) => setSelectedStudentIds(keys as number[]),
          }}
          scroll={{ y: 420 }}
          pagination={{
            current: candidatePage,
            pageSize: candidatePageSize,
            total: assignmentCandidates.length,
            onChange: (p, s) => {
              setCandidatePage(p)
              setCandidatePageSize(s)
            },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          locale={{
            emptyText: (
              <EmptyState height={200} title="暂无可分配学生" desc="全部学生均已分班或没有符合条件的结果" />
            ),
          }}
        />
      </Modal>

    </div>
  )
}
