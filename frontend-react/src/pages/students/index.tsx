import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, App, Button, Dropdown, Form, Input, InputNumber, Modal, Progress, Select, Space, Table, Tabs, Tag } from 'antd'
import { DownloadOutlined, ExportOutlined, ImportOutlined, KeyOutlined, RobotOutlined } from '@ant-design/icons'
import type { TableProps } from 'antd'
import { authApi, fileCenterApi, gaokaoApi, orgApi, organizationApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import StudentScheduleModal from './StudentScheduleModal'
import { ACADEMIC_CONTEXT_CHANGED } from '@/utils/academicContext'
import { GENDER_DICT, STUDENT_STATUS_DICT } from '@/types/dict'
import type { ClassInfo, Grade, OrganizationTreeResult, OrganizationUnit, Student, StudentGradeMembership } from '@/types'

type GenderValue = 'male' | 'female'
type GenderFilter = GenderValue | ''
type CampusFilter = number | ''
type ClassFilter = number | 'unassigned' | ''
type GradeFilter = number | ''
type StudentImportType = 'full' | 'incremental'

interface StudentImportPreview {
  token: string
  import_type: StudentImportType
  total: number
  valid: number
  errors: Array<{ row: number; student_no: string; name: string; errors: string[] }>
  context: { entry_year: number; academic_year: string; term: string }
}

interface StudentFormValues {
  name: string
  student_no?: string
  gender: GenderValue
  grade_id?: number
  class_id?: number
  parent_phone?: string
}

interface StudentSimulationFormValues {
  cohort_label: string
  grade_id: number
  male_count: number
  female_count: number
}

interface StudentAccountFormValues {
  grade_id: number
  initial_password: string
}

type StudentExportKey = 'all' | 'unassigned' | `grade:${number}` | `class:${number}`

export default function StudentsView() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [classes, setClasses] = useState<ClassInfo[]>([])
  const [grades, setGrades] = useState<Grade[]>([])
  const [organizationTree, setOrganizationTree] = useState<OrganizationTreeResult | null>(null)
  const [students, setStudents] = useState<Student[]>([])
  const [academicYear, setAcademicYear] = useState('')
  const [term, setTerm] = useState('1')
  const [scheduleStudent, setScheduleStudent] = useState<Student | null>(null)
  const [subjectChoices, setSubjectChoices] = useState<Map<number, { primary: string; secondary: string[] }>>(new Map())
  const [keyword, setKeyword] = useState('')
  const [campusFilter, setCampusFilter] = useState<CampusFilter>('')
  const [gradeFilter, setGradeFilter] = useState<GradeFilter>('')
  const [classFilter, setClassFilter] = useState<ClassFilter>('')
  const [genderFilter, setGenderFilter] = useState<GenderFilter>('')
  // 点击「查询」后才应用到列表的过滤条件
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [appliedCampusFilter, setAppliedCampusFilter] = useState<CampusFilter>('')
  const [appliedGradeFilter, setAppliedGradeFilter] = useState<GradeFilter>('')
  const [appliedClassFilter, setAppliedClassFilter] = useState<ClassFilter>('')
  const [appliedGenderFilter, setAppliedGenderFilter] = useState<GenderFilter>('')
  const [updatingIds, setUpdatingIds] = useState<Record<number, boolean>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dialogVisible, setDialogVisible] = useState(false)
  const [simulationOpen, setSimulationOpen] = useState(false)
  const [simulationSaving, setSimulationSaving] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [accountSaving, setAccountSaving] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [form] = Form.useForm<StudentFormValues>()
  const [simulationForm] = Form.useForm<StudentSimulationFormValues>()
  const [accountForm] = Form.useForm<StudentAccountFormValues>()
  const formGradeId = Form.useWatch('grade_id', form)
  const simulationCohortLabel = Form.useWatch('cohort_label', simulationForm)
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [exportScopeKey, setExportScopeKey] = useState<StudentExportKey>('all')
  const [exportSubmitting, setExportSubmitting] = useState(false)
  const [exportDoneOpen, setExportDoneOpen] = useState(false)
  const [exportDoneInfo, setExportDoneInfo] = useState<{
    jobTypeLabel: string
    directionLabel: string
    scope: string
    fileName?: string
  } | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importType, setImportType] = useState<StudentImportType>('full')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<StudentImportPreview | null>(null)
  const [importTask, setImportTask] = useState<{ task_id: string; status: string; processed: number; total: number; success: number; failed: number } | null>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [activeTab, setActiveTab] = useState('students')
  const [memberships, setMemberships] = useState<StudentGradeMembership[]>([])
  const [membershipLoading, setMembershipLoading] = useState(false)
  const importInputRef = useRef<HTMLInputElement>(null)

  const filteredStudents = useMemo(() => {
    const query = appliedKeyword.trim().toLowerCase()
    return students.filter((item) => {
      const matchesKeyword =
        !query ||
        item.name.toLowerCase().includes(query) ||
        (item.student_no ?? '').toLowerCase().includes(query)
      const matchesCampus = !appliedCampusFilter || item.campus_id === appliedCampusFilter
      const matchesClass =
        appliedClassFilter === '' ||
        (appliedClassFilter === 'unassigned'
          ? !item.class_id
          : item.class_id === appliedClassFilter)
      const matchesGrade = !appliedGradeFilter || item.grade_id === appliedGradeFilter
      const matchesGender = !appliedGenderFilter || item.gender === appliedGenderFilter
      return matchesKeyword && matchesCampus && matchesGrade && matchesClass && matchesGender
    })
  }, [students, appliedKeyword, appliedCampusFilter, appliedGradeFilter, appliedClassFilter, appliedGenderFilter])

  const unassignedCount = useMemo(
    () => students.filter((item) => !item.class_id).length,
    [students],
  )
  const pagedStudents = useMemo(
    () => filteredStudents.slice((page - 1) * pageSize, page * pageSize),
    [filteredStudents, page, pageSize],
  )

  const campusOptions = useMemo(() => Array.from(
    new Map(
      grades
        .filter((grade) => grade.campus_id)
        .map((grade) => [
          grade.campus_id!,
          { label: grade.campus_name || grade.name.split(' · ')[0], value: grade.campus_id! },
        ]),
    ).values(),
  ), [grades])

  const gradeOptions = useMemo(
    () => grades
      .filter((grade) => !campusFilter || grade.campus_id === campusFilter)
      .map((grade) => ({ label: grade.name, value: grade.id })),
    [grades, campusFilter],
  )

  const classOptions = useMemo(
    () => classes
      .filter((item) => (!campusFilter || item.campus_id === campusFilter) && (!gradeFilter || item.grade_id === gradeFilter))
      .map((item) => ({ label: item.name, value: item.id })),
    [classes, campusFilter, gradeFilter],
  )

  const handleSearch = () => {
    setAppliedKeyword(keyword)
    setAppliedCampusFilter(campusFilter)
    setAppliedGradeFilter(gradeFilter)
    setAppliedClassFilter(classFilter)
    setAppliedGenderFilter(genderFilter)
    setPage(1)
  }

  const resetFilters = () => {
    setKeyword('')
    setCampusFilter('')
    setGradeFilter('')
    setClassFilter('')
    setGenderFilter('')
    setAppliedKeyword('')
    setAppliedCampusFilter('')
    setAppliedGradeFilter('')
    setAppliedClassFilter('')
    setAppliedGenderFilter('')
    setPage(1)
  }

  const handleStatusChange = async (id: number, status: string) => {
    setUpdatingIds((prev) => ({ ...prev, [id]: true }))
    try {
      await orgApi.updateStudentStatus(id, status)
      setStudents((prev) => prev.map((s) => (s.id === id ? { ...s, status } : s)))
      message.success('学生状态已更新')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '状态更新失败')
    } finally {
      setUpdatingIds((prev) => ({ ...prev, [id]: false }))
    }
  }

  const loadData = async (refreshAcademicContext = false) => {
    setLoading(true)
    try {
      const academicSettings = await authApi.academicYears(refreshAcademicContext)
      const scopedAcademicYear = academicSettings.current_academic_year
      const scopedTerm = academicSettings.current_term
      if (!scopedAcademicYear) throw new Error('请先在系统配置中设置当前学年')
      setAcademicYear(scopedAcademicYear)
      setTerm(scopedTerm)
      const [gradeList, classList, studentList, orgTree] = await Promise.all([
        orgApi.grades(),
        orgApi.classes({ academic_year: scopedAcademicYear, term: scopedTerm }),
        orgApi.students(undefined, undefined, undefined, { academic_year: scopedAcademicYear, term: scopedTerm }),
        organizationApi.tree().catch(() => null),
      ])
      const choices = scopedAcademicYear
        ? await gaokaoApi.choicesForReview({
            academic_year: scopedAcademicYear,
            term: scopedTerm,
            status_filter: '',
          }).catch(() => [])
        : []
      const choicesByStudent = new Map<number, { primary: string; secondary: string[] }>()
      choices.forEach((choice) => {
        if (choice.status === 'confirmed' || choice.status === 'locked') {
          choicesByStudent.set(choice.student_id, {
            primary: choice.primary_subject_name,
            secondary: choice.secondary_subject_names,
          })
        }
      })
      setSubjectChoices(choicesByStudent)
      setOrganizationTree(orgTree)
      // 年级筛选只保留「年级管理中心下已建年级部」的年级(与教师档案口径一致)
      const gradeUnitNames = (orgTree?.units ?? [])
        .filter((unit) => unit.unit_type === 'grade_group' && unit.status === 'active')
        .map((unit) => unit.name)
      const visibleGrades = gradeList.filter((grade) => {
        const key = ['高一', '高二', '高三'].find((k) => grade.name.includes(k))
        return !key || gradeUnitNames.some((name) => name.includes(key))
      })
      setGrades(visibleGrades.length ? visibleGrades : gradeList)
      setClasses(classList)
      setStudents(studentList)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学生档案加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
    const refreshScope = () => {
      setScheduleStudent(null)
      resetFilters()
      void loadData(true)
    }
    window.addEventListener(ACADEMIC_CONTEXT_CHANGED, refreshScope)
    return () => window.removeEventListener(ACADEMIC_CONTEXT_CHANGED, refreshScope)
  }, [])

  useEffect(() => {
    if (activeTab !== 'memberships') return
    setMembershipLoading(true)
    void orgApi.studentGradeMemberships()
      .then(setMemberships)
      .catch((error) => message.error(error instanceof Error ? error.message : '学生年级关联加载失败'))
      .finally(() => setMembershipLoading(false))
  }, [activeTab])

  useEffect(() => {
    if (!importTask || importTask.status === 'finished') return
    const timer = window.setTimeout(() => {
      void orgApi.studentImportTask(importTask.task_id).then(setImportTask).catch(() => undefined)
    }, 800)
    return () => window.clearTimeout(timer)
  }, [importTask])

  const downloadTemplate = (type: StudentImportType) => {
    const headers = type === 'full'
      ? '学号,姓名,性别,身高,行政班,家长电话\n'
      : '学号,姓名,性别,身份证号,生源学校\n'
    const blob = new Blob([`\ufeff${headers}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = type === 'full' ? '学生全量档案导入模板.csv' : '新生增量导入模板.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  const exportScopeOptions = useMemo(
    () => [
      { value: 'all' as const, label: '全部学生' },
      { value: 'unassigned' as const, label: '待分班' },
      ...grades.map((grade) => ({ value: `grade:${grade.id}` as const, label: `年级 · ${grade.name}` })),
      ...classes.map((item) => ({ value: `class:${item.id}` as const, label: `班级 · ${item.name}` })),
    ],
    [grades, classes],
  )

  const openExport = () => {
    if (appliedClassFilter === 'unassigned') {
      setExportScopeKey('unassigned')
    } else if (typeof appliedClassFilter === 'number') {
      setExportScopeKey(`class:${appliedClassFilter}`)
    } else if (appliedGradeFilter) {
      setExportScopeKey(`grade:${appliedGradeFilter}`)
    } else {
      setExportScopeKey('all')
    }
    setExportModalOpen(true)
  }

  const submitStudentExport = async () => {
    setExportSubmitting(true)
    try {
      const payload = {
        grade_id: exportScopeKey.startsWith('grade:') ? Number(exportScopeKey.slice(6)) : null,
        class_id: exportScopeKey.startsWith('class:') ? Number(exportScopeKey.slice(6)) : null,
        unassigned_only: exportScopeKey === 'unassigned',
      }
      const scopeLabel =
        exportScopeOptions.find((item) => item.value === exportScopeKey)?.label || '全部学生'
      const job = await fileCenterApi.exportStudents(payload)
      setExportModalOpen(false)
      setExportDoneInfo({
        jobTypeLabel: job.job_type_label || '导出学生',
        directionLabel: '导出',
        scope: job.scope || scopeLabel,
        fileName: job.file_name || undefined,
      })
      setExportDoneOpen(true)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建导出任务失败')
      return Promise.reject()
    } finally {
      setExportSubmitting(false)
    }
  }

  const openImport = (type: StudentImportType) => {
    setImportType(type)
    setImportFile(null)
    setImportPreview(null)
    setImportTask(null)
    setImportOpen(true)
  }

  const validateImport = async () => {
    if (!importFile) {
      message.warning('请选择 Excel 或 ZIP 文件')
      return
    }
    setImportBusy(true)
    try {
      const preview = await orgApi.validateStudentImport(importType, importFile)
      setImportPreview(preview)
      if (preview.errors.length) message.warning(`发现 ${preview.errors.length} 行数据需要修正`)
      else message.success('数据校验通过')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '数据校验失败')
    } finally {
      setImportBusy(false)
    }
  }

  const confirmImport = async () => {
    if (!importPreview || importPreview.errors.length) return
    setImportBusy(true)
    try {
      const task = await orgApi.confirmStudentImport(importPreview.token)
      setImportTask(task)
      setImportPreview(null)
      message.success('导入任务已创建，正在后台处理')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建导入任务失败')
    } finally {
      setImportBusy(false)
    }
  }

  const openCreate = () => {
    form.setFieldsValue({
      name: '',
      student_no: '',
      gender: 'male',
      grade_id: undefined,
      class_id: undefined,
      parent_phone: '',
    })
    setDialogVisible(true)
  }

  const createStudent = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    if (!values.name.trim()) {
      message.warning('请输入学生姓名')
      return
    }
    setSaving(true)
    try {
      await orgApi.createStudent({
        name: values.name.trim(),
        student_no: values.student_no?.trim() || undefined,
        gender: values.gender,
        grade_id: values.grade_id ?? null,
        class_id: values.class_id ?? null,
        parent_phone: values.parent_phone?.trim() || undefined,
      })
      setDialogVisible(false)
      message.success(values.class_id ? '学生档案已创建' : '学生已加入待分班名单')
      await loadData()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学生创建失败')
    } finally {
      setSaving(false)
    }
  }

  const organizationUnits = useMemo(() => {
    const flatten = (items: OrganizationUnit[]): OrganizationUnit[] => items.flatMap((item) => [item, ...flatten(item.children || [])])
    return flatten(organizationTree?.units || [])
  }, [organizationTree])

  const simulationCohortOptions = useMemo(() => Array.from(new Set(
    organizationUnits
      .filter((item) => item.unit_type === 'grade_group' && item.status === 'active' && item.cohort_label)
      .map((item) => item.cohort_label as string),
  )).sort((a, b) => Number(b) - Number(a)).map((value) => ({ label: `${value}届`, value })), [organizationUnits])

  const simulationGradeOptions = useMemo(() => {
    const gradeIds = new Set(organizationUnits
      .filter((item) => item.unit_type === 'grade_group' && item.status === 'active' && item.cohort_label === simulationCohortLabel)
      .map((item) => item.grade_id)
      .filter((value): value is number => value != null))
    return grades.filter((grade) => gradeIds.has(grade.id)).map((grade) => ({ label: grade.name, value: grade.id }))
  }, [grades, organizationUnits, simulationCohortLabel])

  const openSimulation = () => {
    simulationForm.resetFields()
    simulationForm.setFieldsValue({
      cohort_label: simulationCohortOptions[0]?.value,
      male_count: 0,
      female_count: 0,
    })
    setSimulationOpen(true)
  }

  const simulateStudents = async () => {
    const values = await simulationForm.validateFields().catch(() => null)
    if (!values) return
    setSimulationSaving(true)
    try {
      const result = await orgApi.simulateStudents(values)
      setSimulationOpen(false)
      message.success(`已生成 ${result.created} 名模拟学生，当前均为待分班状态`)
      await loadData()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '模拟学生生成失败')
    } finally {
      setSimulationSaving(false)
    }
  }

  const openAccountProvision = () => {
    accountForm.resetFields()
    accountForm.setFieldsValue({ grade_id: undefined, initial_password: '123456' })
    setAccountOpen(true)
  }

  const provisionStudentAccounts = async () => {
    const values = await accountForm.validateFields().catch(() => null)
    if (!values) return
    setAccountSaving(true)
    try {
      const result = await orgApi.provisionStudentAccounts(values)
      setAccountOpen(false)
      message.success(`已为 ${result.created + result.reset} 名学生开通账号，登录名使用学生学号`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学生账号开通失败')
    } finally {
      setAccountSaving(false)
    }
  }

  const columns: TableProps<Student>['columns'] = [
    { title: '学号', dataIndex: 'student_no', width: 160, render: (value: string) => value || '—' },
    { title: '姓名', dataIndex: 'name', width: 120 },
    {
      title: '年级',
      dataIndex: 'grade_name',
      width: 120,
      render: (value: string | null, record) => (
        <span className={record.grade_id ? undefined : 'pending-text'}>
          {value || '待分配年级'}
        </span>
      ),
    },
    {
      title: '行政班',
      key: 'class',
      width: 160,
      render: (_, record) => (
        <span className={record.class_id ? undefined : 'pending-text'}>
          {record.class_name || '待分班'}
        </span>
      ),
    },
    {
      title: '首选科目（1）',
      key: 'primary_subject',
      width: 130,
      render: (_, record) => subjectChoices.get(record.id)?.primary || '—',
    },
    {
      title: '再选科目（2）',
      key: 'secondary_subjects',
      width: 180,
      render: (_, record) => subjectChoices.get(record.id)?.secondary.join('、') || '—',
    },
    {
      title: '性别',
      dataIndex: 'gender',
      width: 90,
      render: (value: string) => <DictTag dict={GENDER_DICT} value={value} />,
    },
    {
      title: '家长电话',
      dataIndex: 'parent_phone',
      width: 160,
      render: (value: string) => value || '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (_value: string, record) => (
        <Select
          size="small"
          value={record.status || 'studying'}
          onChange={(v) => handleStatusChange(record.id, v)}
          loading={!!updatingIds[record.id]}
          disabled={!!updatingIds[record.id]}
          options={Object.entries(STUDENT_STATUS_DICT).map(([k, v]) => ({
            label: v.label,
            value: k,
          }))}
        />
      ),
    },
    {
      title: '操作', key: 'schedule', width: 120, fixed: 'right',
      render: (_, record) => <Button type="primary" size="small" disabled={!academicYear || loading}
        onClick={() => setScheduleStudent(record)}>查询课表</Button>,
    },
  ]

  return (
    <div className="zh-page">
      <PageHeader
        title="学生档案"
        extra={
          <Space>
            <Dropdown
              menu={{
                items: [
                  { key: 'full', label: '全量档案导入模板', onClick: () => downloadTemplate('full') },
                  { key: 'incremental', label: '新生增量导入模板', onClick: () => downloadTemplate('incremental') },
                ],
              }}
            >
              <Button icon={<DownloadOutlined />}>模板下载</Button>
            </Dropdown>
            <Button icon={<ExportOutlined />} onClick={openExport}>导出 Excel</Button>
            <Button icon={<ImportOutlined />} onClick={() => openImport('full')}>导入学生</Button>
            <Button icon={<RobotOutlined />} onClick={openSimulation}>批量生成学生</Button>
            <Button icon={<KeyOutlined />} onClick={openAccountProvision}>开通学生登录</Button>
            <Button type="primary" onClick={openCreate}>新增学生</Button>
          </Space>
        }
      />
      <p className="zh-page-desc">
        先维护全校学生名册；学生可暂不指定行政班，随后进入“行政班管理”统一安排。
      </p>

      <div className="zh-stat-strip">
        <span>
          学生总数 <strong>{students.length}</strong>
        </span>
        <span>
          待分班 <strong>{unassignedCount}</strong>
        </span>
      </div>

      <FilterCard>
        <div className="zh-filter-row">
          <label className="zh-filter-field">
            <span>学生</span>
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              allowClear
              placeholder="姓名或学号"
              style={{ width: 220 }}
            />
          </label>
          <label className="zh-filter-field">
            <span>校区</span>
            <Select
              value={campusFilter || undefined}
              onChange={(value) => {
                setCampusFilter((value ?? '') as CampusFilter)
                setGradeFilter('')
                setClassFilter('')
              }}
              allowClear
              placeholder="全部校区"
              style={{ width: 150 }}
              options={campusOptions}
            />
          </label>
          <label className="zh-filter-field">
            <span>年级</span>
            <Select
              value={gradeFilter || undefined}
              onChange={(value) => {
                setGradeFilter((value ?? '') as GradeFilter)
                setClassFilter('')
              }}
              allowClear
              placeholder="全部年级"
              style={{ width: 170 }}
              options={gradeOptions}
            />
          </label>
          <label className="zh-filter-field">
            <span>行政班</span>
            <Select
              value={classFilter || undefined}
              onChange={(value) => setClassFilter((value ?? '') as ClassFilter)}
              allowClear
              placeholder="全部行政班"
              style={{ width: 180 }}
              options={[{ label: '待分班', value: 'unassigned' }, ...classOptions]}
            />
          </label>
          <label className="zh-filter-field">
            <span>性别</span>
            <Select
              value={genderFilter || undefined}
              onChange={(v) => setGenderFilter((v ?? '') as GenderFilter)}
              allowClear
              placeholder="全部性别"
              style={{ width: 140 }}
              options={[
                { label: '男', value: 'male' },
                { label: '女', value: 'female' },
              ]}
            />
          </label>
          <Button type="primary" onClick={handleSearch}>
            查询
          </Button>
          <Button onClick={resetFilters}>重置</Button>
          <span className="zh-filter-count">当前 {filteredStudents.length} 人</span>
        </div>
      </FilterCard>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[{ key: 'students', label: '学生档案' }, { key: 'memberships', label: '学生年级关联' }]}
        style={{ marginBottom: 0 }}
      />

      <TableCard>
        {activeTab === 'students' ? <Table<Student>
          rowKey="id"
          columns={columns}
          dataSource={pagedStudents}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: filteredStudents.length,
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
                title="暂无学生档案"
                desc="点击右上角“新增学生”建立档案"
              />
            ),
          }}
        /> : <Table<StudentGradeMembership>
          rowKey="id"
          loading={membershipLoading}
          dataSource={memberships}
          pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
          columns={[
            { title: '学号', dataIndex: 'student_no', width: 160, render: (value) => value || '—' },
            { title: '姓名', dataIndex: 'student_name', width: 120 },
            { title: '年级部', dataIndex: 'grade_unit_name', width: 220 },
            { title: '年级', dataIndex: 'grade_name', width: 140 },
            { title: '届别', dataIndex: 'cohort_label', width: 100, render: (value) => value || '—' },
            { title: '学年', dataIndex: 'academic_year', width: 140 },
            { title: '状态', dataIndex: 'status', width: 100, render: (value) => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '有效' : '已归档'}</Tag> },
          ]}
          locale={{ emptyText: <EmptyState height={220} title="暂无学生年级关联" desc="学生指定年级或分班后会自动建立关系" /> }}
        />}
      </TableCard>

      {scheduleStudent && <StudentScheduleModal student={scheduleStudent} academicYear={academicYear}
        term={term} onClose={() => setScheduleStudent(null)} />}

      <Modal
        title="新增学生档案"
        open={dialogVisible}
        onCancel={() => setDialogVisible(false)}
        onOk={createStudent}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={500}
        forceRender
      >
        <Form form={form} layout="vertical" name="createStudent">
          <div className="zh-form-grid">
            <Form.Item
              name="name"
              label="姓名"
              rules={[{ required: true, whitespace: true, message: '请输入学生姓名' }]}
            >
              <Input placeholder="请输入姓名" maxLength={50} />
            </Form.Item>
            <Form.Item name="student_no" label="学号">
              <Input placeholder="选填" maxLength={30} />
            </Form.Item>
            <Form.Item
              name="gender"
              label="性别"
              rules={[{ required: true, message: '请选择性别' }]}
            >
              <Select
                options={[
                  { label: '男', value: 'male' },
                  { label: '女', value: 'female' },
                ]}
              />
            </Form.Item>
            <Form.Item name="grade_id" label="年级">
              <Select
                allowClear
                placeholder="暂不指定年级"
                options={grades.map((grade) => ({ label: grade.name, value: grade.id }))}
              />
            </Form.Item>
            <Form.Item name="class_id" label="行政班（可稍后分配）">
              <Select
                allowClear
                placeholder="暂不分班"
                options={classes
                  .filter((item) => !formGradeId || item.grade_id === formGradeId)
                  .map((c) => ({ label: c.name, value: c.id }))}
              />
            </Form.Item>
            <Form.Item name="parent_phone" label="家长电话" className="zh-form-wide">
              <Input placeholder="选填" maxLength={20} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal
        title="批量生成模拟学生"
        open={simulationOpen}
        onCancel={() => !simulationSaving && setSimulationOpen(false)}
        onOk={() => void simulateStudents()}
        okText="开始生成"
        cancelText="取消"
        confirmLoading={simulationSaving}
        width={520}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          message="用于快速准备排课和分班测试数据"
          description="生成的学生会自动关联到所选届别和年级，行政班暂不指定，后续可在行政班管理中统一分班。"
          style={{ marginBottom: 16 }}
        />
        {!simulationCohortOptions.length && (
          <Alert type="warning" showIcon message="暂无可用届别" description="请先在组织机构中配置当前学年的年级部和届别。" style={{ marginBottom: 16 }} />
        )}
        <Form form={simulationForm} layout="vertical">
          <Form.Item name="cohort_label" label="届别" rules={[{ required: true, message: '请选择届别' }]}>
            <Select
              placeholder="请选择届别"
              options={simulationCohortOptions}
              disabled={!simulationCohortOptions.length}
              onChange={() => simulationForm.setFieldValue('grade_id', undefined)}
            />
          </Form.Item>
          <Form.Item name="grade_id" label="年级" rules={[{ required: true, message: '请选择年级' }]}>
            <Select
              placeholder={simulationCohortLabel ? '请选择年级' : '请先选择届别'}
              options={simulationGradeOptions}
              disabled={!simulationCohortLabel || !simulationGradeOptions.length}
              notFoundContent="该届别暂无对应年级部"
            />
          </Form.Item>
          <div className="zh-form-grid">
            <Form.Item name="male_count" label="男生人数" rules={[{ required: true, message: '请输入男生人数' }]}>
              <InputNumber min={0} max={5000} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="female_count" label="女生人数" rules={[{ required: true, message: '请输入女生人数' }]}>
              <InputNumber min={0} max={5000} precision={0} style={{ width: '100%' }} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <Modal
        title="开通学生登录账号"
        open={accountOpen}
        onCancel={() => !accountSaving && setAccountOpen(false)}
        onOk={() => void provisionStudentAccounts()}
        okText="开通账号"
        cancelText="取消"
        confirmLoading={accountSaving}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          message="按年级批量开通学生端账号"
          description="学生使用学号登录选科页面；已存在账号会重置为本次初始密码。请开通后及时通知学生修改密码。"
          style={{ marginBottom: 16 }}
        />
        <Form form={accountForm} layout="vertical">
          <Form.Item name="grade_id" label="年级" rules={[{ required: true, message: '请选择年级' }]}>
            <Select placeholder="请选择年级" options={grades.map((grade) => ({ label: grade.name, value: grade.id }))} />
          </Form.Item>
          <Form.Item
            name="initial_password"
            label="统一初始密码"
            rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="导出学生档案"
        open={exportModalOpen}
        onCancel={() => !exportSubmitting && setExportModalOpen(false)}
        okText="导出"
        cancelText="取消"
        confirmLoading={exportSubmitting}
        centered
        width={420}
        destroyOnClose
        onOk={() => submitStudentExport()}
      >
        <p className="zh-page-desc" style={{ marginBottom: 12 }}>
          先选择导出范围（全部、待分班、年级或班级），再点「导出」。
        </p>
        <Select
          style={{ width: '100%' }}
          value={exportScopeKey}
          onChange={(value) => setExportScopeKey(value as StudentExportKey)}
          options={exportScopeOptions}
        />
      </Modal>

      <Modal
        title="已提交到文件中心"
        open={exportDoneOpen}
        onCancel={() => setExportDoneOpen(false)}
        centered
        width={440}
        destroyOnClose
        footer={[
          <Button key="stay" onClick={() => setExportDoneOpen(false)}>
            稍后查看
          </Button>,
          <Button
            key="go"
            type="primary"
            onClick={() => {
              setExportDoneOpen(false)
              navigate('/file-center')
            }}
          >
            前往文件中心
          </Button>,
        ]}
      >
        <p className="zh-page-desc" style={{ marginBottom: 12 }}>
          任务已创建，可在文件中心查看进度并下载。
        </p>
        <div
          style={{
            display: 'grid',
            gap: 10,
            padding: '12px 14px',
            border: '1px solid #e2e8f0',
            borderRadius: 10,
            background: '#f8fafc',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
            <span style={{ color: '#64748b' }}>操作</span>
            <strong>{exportDoneInfo?.directionLabel || '导出'}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
            <span style={{ color: '#64748b' }}>文件类型</span>
            <strong>{exportDoneInfo?.jobTypeLabel || '导出学生'}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
            <span style={{ color: '#64748b' }}>范围</span>
            <strong>{exportDoneInfo?.scope || '—'}</strong>
          </div>
          {exportDoneInfo?.fileName ? (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13 }}>
              <span style={{ color: '#64748b' }}>文件名</span>
              <strong style={{ textAlign: 'right', wordBreak: 'break-all' }}>{exportDoneInfo.fileName}</strong>
            </div>
          ) : null}
        </div>
      </Modal>

      <Modal
        title="导入学生档案"
        open={importOpen}
        onCancel={() => { if (!importTask || importTask.status === 'finished') setImportOpen(false) }}
        footer={importTask ? null : [
          <Button key="cancel" onClick={() => setImportOpen(false)}>取消</Button>,
          <Button key="validate" type="primary" loading={importBusy} disabled={!importFile} onClick={() => void validateImport()}>校验数据</Button>,
          <Button key="confirm" type="primary" loading={importBusy} disabled={!importPreview || importPreview.errors.length > 0} onClick={() => void confirmImport()}>确认导入</Button>,
        ]}
        width={680}
        centered
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Select
            value={importType}
            onChange={(value) => { setImportType(value); setImportFile(null); setImportPreview(null) }}
            style={{ width: '100%' }}
            options={[
              { label: '全量档案导入（新增或更新完整档案）', value: 'full' },
              { label: '新生增量导入（只新增，不覆盖已有档案）', value: 'incremental' },
            ]}
          />
          {!importTask && (
            <div className="zh-import-dropzone" onClick={() => importInputRef.current?.click()}>
              <input ref={importInputRef} type="file" accept=".xlsx,.csv,.zip" hidden onChange={(event) => setImportFile(event.target.files?.[0] ?? null)} />
              <ImportOutlined style={{ fontSize: 28 }} />
              <div>{importFile ? importFile.name : '点击选择 Excel 或 ZIP 文件'}</div>
              <small>{importType === 'full' ? '全量模板包含行政班，班级按当前配置届别校验' : '增量模板只新增学生，不覆盖本地档案'}</small>
            </div>
          )}
          {importPreview && (
            <div>
              <Space wrap>
                <Tag color="blue">当前届别 {importPreview.context.entry_year}届</Tag>
                <Tag>{importPreview.context.academic_year} · 第{importPreview.context.term}学期</Tag>
                <Tag color={importPreview.errors.length ? 'red' : 'green'}>通过 {importPreview.valid} / {importPreview.total}</Tag>
              </Space>
              {importPreview.errors.length > 0 && <div className="zh-import-errors">发现 {importPreview.errors.length} 行错误，请修正后重新上传。</div>}
            </div>
          )}
          {importTask && (
            <div>
              <div style={{ marginBottom: 8 }}>正在后台导入，当前配置：{importTask.total} 条数据</div>
              <Progress percent={importTask.total ? Math.round(importTask.processed / importTask.total * 100) : 0} status={importTask.status === 'finished' ? 'success' : 'active'} />
              <div className="zh-import-progress-meta">已处理 {importTask.processed} / {importTask.total} 条 · 成功 {importTask.success} 条 · 失败 {importTask.failed} 条</div>
              {importTask.status === 'finished' && <Button type="primary" onClick={() => { setImportOpen(false); void loadData() }}>完成</Button>}
            </div>
          )}
        </Space>
      </Modal>
    </div>
  )
}
