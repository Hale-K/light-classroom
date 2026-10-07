import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Checkbox, Form, InputNumber, Modal, Progress, Radio, Segmented, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { schedulingApi } from '@/api'
import type { ClassInfo, CourseHourPlanInfo, EveningParity, SubjectInfo, WeekParity } from '@/types'
import SelectEmptyGuide from '@/components/SelectEmptyGuide'
import './walk-course-hours.css'
import './course-hours.css'

interface CourseHoursPanelProps {
  classes: ClassInfo[]
  subjects: SubjectInfo[]
  academicYear: string
  term: string
  classId?: number
  onClassChange?: (classId?: number) => void
  classOptions?: Array<{ label: string; value: number }>
  onInherited?: () => Promise<void> | void
  /** 每周白天课位容量（来自课位结构）；未配置课位结构时不传，弹窗内不显示容量参照。 */
  daytimeCapacity?: number
}

type EveningParityChoice = EveningParity

interface CourseHourFormValues {
  class_id: number
  subject_id: number
  weekday_periods: number
  saturday_periods: number
  weekly_periods: number
  week_parity: WeekParity
  evening_periods: number
  evening_parity?: EveningParityChoice
}

const parityLabels: Record<WeekParity, string> = { all: '每周', odd: '单周', even: '双周' }

const hasHalfDaytime = (weekday: number, saturday: number) =>
  [weekday, saturday].some((value) => value % 1 !== 0)

const formatPeriods = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1))

const eveningText = (row: CourseHourPlanInfo): string => {
  const mode = row.evening_parity
    ?? (row.evening_periods_odd && row.evening_periods_even
      ? (row.week_parity !== 'all' ? 'either' : 'all')
      : (row.evening_periods_odd ? 'odd' : row.evening_periods_even ? 'even' : 'all'))
  if (mode === 'either') return '0.5 节（无规定）'
  if (mode === 'odd') return '0.5 节（单周）'
  if (mode === 'even') return '0.5 节（双周）'
  if (row.evening_periods_odd && row.evening_periods_even) return '1 节（每周）'
  return '0 节'
}

const describePlan = (row: CourseHourPlanInfo): string =>
  `${parityLabels[row.week_parity]} 工作日 ${formatPeriods(row.weekday_periods)} 节 · 周六 ${formatPeriods(row.saturday_periods)} 节 · 晚课 ${eveningText(row)}`

/** 课表行 → 弹窗表单值（编辑与“同科目参考默认”共用） */
function planToFormValues(row: CourseHourPlanInfo): Partial<CourseHourFormValues> {
  const both = Boolean(row.evening_periods_odd && row.evening_periods_even)
  const stored = row.evening_parity
  const eveningParity: EveningParityChoice = stored
    ? stored
    : both
      ? (row.week_parity !== 'all' ? 'either' : 'all')
      : (row.evening_periods_odd && !row.evening_periods_even ? 'odd' : 'even')
  const isHalfEvening = eveningParity === 'either' || eveningParity === 'odd' || eveningParity === 'even'
  return {
    class_id: row.class_id,
    subject_id: row.subject_id,
    weekday_periods: row.weekday_periods,
    saturday_periods: row.saturday_periods,
    weekly_periods: row.weekly_periods,
    week_parity: row.week_parity,
    evening_periods: both || row.evening_periods_odd || row.evening_periods_even
      ? (isHalfEvening ? 0.5 : 1)
      : 0,
    evening_parity: eveningParity === 'all' ? 'either' : eveningParity,
  }
}

export default function CourseHoursPanel({
  classes,
  subjects,
  academicYear,
  term,
  classId,
  onClassChange,
  classOptions,
  onInherited,
  daytimeCapacity,
}: CourseHoursPanelProps) {
  const { message } = App.useApp()
  const [allPlans, setAllPlans] = useState<CourseHourPlanInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<CourseHourPlanInfo>()
  const [autoTarget, setAutoTarget] = useState<CourseHourPlanInfo>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [inheritOpen, setInheritOpen] = useState(false)
  const [inheriting, setInheriting] = useState(false)
  const [inheritTypes, setInheritTypes] = useState(['course_hours', 'assignments'])
  const [form] = Form.useForm<CourseHourFormValues>()
  const saveModeRef = useRef<'save' | 'continue' | null>(null)
  const weekdayPeriods = Form.useWatch('weekday_periods', form) ?? 0
  const saturdayPeriods = Form.useWatch('saturday_periods', form) ?? 0
  const eveningPeriods = Form.useWatch('evening_periods', form) ?? 0
  const formClassId = Form.useWatch('class_id', form) as number | undefined
  const formSubjectId = Form.useWatch('subject_id', form) as number | undefined
  const hasHalfPeriod = hasHalfDaytime(weekdayPeriods, saturdayPeriods)

  const rows = useMemo(
    () => (classId ? allPlans.filter((row) => row.class_id === classId) : allPlans),
    [allPlans, classId],
  )

  useEffect(() => {
    const currentParity = form.getFieldValue('week_parity') as WeekParity | undefined
    if (!hasHalfPeriod && currentParity && currentParity !== 'all') {
      form.setFieldValue('week_parity', 'all')
    }
  }, [form, hasHalfPeriod])

  useEffect(() => {
    if (eveningPeriods === 0.5) {
      const current = form.getFieldValue('evening_parity') as EveningParityChoice | undefined
      if (!current || current === 'all') {
        form.setFieldValue('evening_parity', 'either')
      }
    } else if (eveningPeriods === 1) {
      form.setFieldValue('evening_parity', 'all')
    }
  }, [eveningPeriods, form])

  // 新增模式下选完班级+科目：已有同组合方案则转更新模式；否则带出同科目其他班级的配置作默认
  useEffect(() => {
    if (!open || editing) return
    if (!formClassId || !formSubjectId) {
      setAutoTarget(undefined)
      return
    }
    const siblings = allPlans.filter((row) => row.class_id === formClassId && row.subject_id === formSubjectId)
    if (!siblings.length) {
      setAutoTarget(undefined)
      const reference = allPlans.find((row) => row.subject_id === formSubjectId && row.class_id !== formClassId)
      if (reference) form.setFieldsValue(planToFormValues(reference))
      return
    }
    const currentParity = (form.getFieldValue('week_parity') as WeekParity | undefined) ?? 'all'
    const target = siblings.find((row) => row.week_parity === currentParity) ?? siblings[0]
    setAutoTarget(target)
    form.setFieldsValue(planToFormValues(target))
  }, [open, editing, formClassId, formSubjectId, allPlans, form])

  const load = async () => {
    setLoading(true)
    try {
      setAllPlans(await schedulingApi.courseHours({ academic_year: academicYear, term }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课时方案加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [academicYear, term])

  const close = () => {
    setOpen(false)
    setEditing(undefined)
    setAutoTarget(undefined)
    form.resetFields()
  }

  const openCreate = () => {
    setEditing(undefined)
    setAutoTarget(undefined)
    form.resetFields()
    form.setFieldsValue({
      class_id: classId,
      weekday_periods: 4,
      saturday_periods: 0,
      weekly_periods: 4,
      week_parity: 'all',
      evening_periods: 0,
      evening_parity: 'either',
    })
    setOpen(true)
  }

  const openEdit = (row: CourseHourPlanInfo) => {
    setEditing(row)
    setAutoTarget(undefined)
    form.setFieldsValue(planToFormValues(row))
    setOpen(true)
  }

  const submit = async (values: CourseHourFormValues) => {
    setSaving(true)
    try {
      let eveningPeriodsOdd = 0
      let eveningPeriodsEven = 0
      if (values.evening_periods === 1) {
        eveningPeriodsOdd = 1
        eveningPeriodsEven = 1
      } else if (values.evening_periods === 0.5) {
        if (values.evening_parity === 'odd') {
          eveningPeriodsOdd = 1
        } else if (values.evening_parity === 'even') {
          eveningPeriodsEven = 1
        } else {
          // 空 / either / all：单双由排课程序决定
          eveningPeriodsOdd = 1
          eveningPeriodsEven = 1
        }
      }
      const target = editing ?? autoTarget
      await schedulingApi.saveCourseHour({
        id: target?.id,
        weekly_periods: values.weekday_periods + values.saturday_periods,
        class_id: values.class_id,
        subject_id: values.subject_id,
        weekday_periods: values.weekday_periods,
        saturday_periods: values.saturday_periods,
        week_parity: values.week_parity,
        academic_year: academicYear,
        term,
        evening_parity: values.evening_periods === 0.5
          ? (values.evening_parity === 'odd' || values.evening_parity === 'even' ? values.evening_parity : 'either')
          : (values.evening_periods === 1 ? 'all' : 'all'),
        evening_periods_odd: eveningPeriodsOdd,
        evening_periods_even: eveningPeriodsEven,
      })
      if (saveModeRef.current === 'continue' && !target) {
        message.success('已保存，可继续录入下一科目')
        form.setFieldValue('subject_id', undefined)
        const subjectField = form.getFieldInstance('subject_id') as { focus?: () => void } | null
        subjectField?.focus?.()
        await load()
      } else {
        message.success(target ? '课时方案已更新' : '课时方案已保存')
        close()
        await load()
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课时方案保存失败')
    } finally {
      saveModeRef.current = null
      setSaving(false)
    }
  }

  const remove = async (row: CourseHourPlanInfo) => {
    try {
      await schedulingApi.deleteCourseHour(row.id)
      message.success('课时方案已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课时方案删除失败')
    }
  }

  const inheritFromPreviousTerm = async () => {
    if (!inheritTypes.length) {
      message.warning('至少选择一种要沿用的数据')
      return
    }
    setInheriting(true)
    try {
      const currentGradeId = classes.find((item) => item.id === classId)?.grade_id ?? classes[0]?.grade_id
      const gradeClassIds = currentGradeId == null
        ? classes.map((item) => item.id)
        : classes.filter((item) => item.grade_id === currentGradeId).map((item) => item.id)
      const result = await schedulingApi.inheritTermData({
        academic_year: academicYear,
        from_term: term === '2' ? '1' : '2',
        to_term: term,
        class_ids: gradeClassIds.length ? gradeClassIds : undefined,
        copy_course_hours: inheritTypes.includes('course_hours'),
        copy_assignments: inheritTypes.includes('assignments'),
        copy_rules: inheritTypes.includes('rules'),
      })
      message.success(`已沿用：课时方案 ${result.course_hours_created} 条，任教关系新增 ${result.assignments_created} 条、更新 ${result.assignments_updated} 条，排课规则 ${result.rule_groups_created_or_copied} 组`)
      setInheritOpen(false)
      await load()
      await onInherited?.()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学期配置沿用失败')
    } finally {
      setInheriting(false)
    }
  }

  const columns: ColumnsType<CourseHourPlanInfo> = [
    { title: '班级', dataIndex: 'class_name', key: 'class_name', width: 180, render: (value) => <strong>{value || '未知班级'}</strong> },
    { title: '科目', dataIndex: 'subject_name', key: 'subject_name', width: 140 },
    { title: '工作日', dataIndex: 'weekday_periods', key: 'weekday_periods', width: 110, align: 'center', render: (value: number) => `${value} 节` },
    { title: '周末', dataIndex: 'saturday_periods', key: 'saturday_periods', width: 100, align: 'center', render: (value: number) => `${value} 节` },
    { title: '白天合计', dataIndex: 'weekly_periods', key: 'weekly_periods', width: 100, align: 'center', render: (value: number) => <strong className="walk-hours-total-number">{formatPeriods(value)}</strong> },
    { title: '晚课', key: 'evening_periods', width: 170, align: 'center', render: (_, row) => eveningText(row) },
    { title: '白天周次', dataIndex: 'week_parity', key: 'week_parity', width: 140, align: 'center', render: (value: WeekParity, row) => {
      const half = hasHalfDaytime(row.weekday_periods, row.saturday_periods)
      const label = value === 'all' && half ? '无规定' : parityLabels[value]
      return <Tag color={value === 'all' ? 'blue' : 'gold'}>{label}</Tag>
    } },
    {
      title: '操作', key: 'actions', width: 130, align: 'right',
      render: (_, row) => <Space size={4}>
        <Button type="link" size="small" onClick={() => openEdit(row)}>编辑</Button>
        <Button type="link" size="small" danger onClick={() => void remove(row)}>删除</Button>
      </Space>,
    },
  ]

  const weekdayTotal = rows.reduce((sum, row) => sum + row.weekday_periods, 0)
  const saturdayTotal = rows.reduce((sum, row) => sum + row.saturday_periods, 0)
  const daytimeTotal = weekdayTotal + saturdayTotal

  const isUpdate = Boolean(editing || autoTarget)
  const updateTargetId = (editing ?? autoTarget)?.id
  const classConfiguredOther = allPlans
    .filter((row) => row.class_id === formClassId && row.id !== updateTargetId)
    .reduce((sum, row) => sum + row.weekday_periods + row.saturday_periods, 0)
  const daytimeAfterSave = classConfiguredOther + weekdayPeriods + saturdayPeriods

  return (
    <section className="sk-hours walk-hours admin-hours">
      <div className="sk-hours-intro">
        <div>
          <h2>行政班课时</h2>
          <p>工作日、周末分别设置，晚自习单独安排。</p>
        </div>
        <Space wrap>
          <Select
            allowClear
            value={classId}
            onChange={(next) => onClassChange?.(next)}
            placeholder="全部班级"
            style={{ width: 220 }}
            popupMatchSelectWidth={280}
            options={classOptions?.length
              ? classOptions
              : classes.map((item) => ({ label: item.name, value: item.id }))}
          />
          <Button onClick={() => void load()} loading={loading}>刷新</Button>
          {term === '2' && (
            <Button onClick={() => setInheritOpen(true)}>沿用第 1 学期年级配置</Button>
          )}
          <Button type="primary" onClick={openCreate}>新增课时</Button>
        </Space>
      </div>
      <div className="walk-hours-meta">
        <div><strong>{rows.length}</strong><span>条课时方案</span></div>
        <div><strong>{weekdayTotal}</strong><span>工作日课时</span></div>
        <div><strong>{saturdayTotal}</strong><span>周末课时</span></div>
        <div><strong>{daytimeTotal}</strong><span>白天课时合计</span></div>
        <div className="walk-hours-term">{academicYear} · 第 {term} 学期</div>
      </div>
      <div className="walk-hours-table-wrap">
        <div className="walk-hours-table-heading"><h3>班级课时</h3><span>单位：节 · 周末当前排周六</span></div>
      <Table<CourseHourPlanInfo>
        className="sk-hours-table"
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        scroll={{ x: 1070 }}
        pagination={{
          current: page,
          pageSize,
          total: rows.length,
          onChange: (p, s) => { setPage(p); setPageSize(s) },
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
        locale={{ emptyText: '暂无课时方案，请先新增班级课程课时' }}
      />
      </div>
      <Modal
        title={isUpdate ? '编辑行政班课时' : '新增行政班课时'}
        className="walk-hours-modal admin-hours-modal"
        open={open}
        centered
        width={560}
        onCancel={close}
        onOk={() => { saveModeRef.current = 'save'; form.submit() }}
        okText={isUpdate ? '更新' : '保存'}
        cancelText="取消"
        confirmLoading={saving}
        footer={!isUpdate ? (
          <Space>
            <Button onClick={close}>取消</Button>
            <Button loading={saving && saveModeRef.current === 'save'} onClick={() => { saveModeRef.current = 'save'; form.submit() }}>保存</Button>
            <Button type="primary" loading={saving && saveModeRef.current === 'continue'} onClick={() => { saveModeRef.current = 'continue'; form.submit() }}>保存并继续</Button>
          </Space>
        ) : undefined}
      >
        <div className="walk-hours-modal-context"><span>行政班课时方案</span><span>{academicYear} · 第 {term} 学期</span></div>
        <Form form={form} layout="vertical" onFinish={submit}>
          {autoTarget && !editing && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="该班级此科目已有课时方案，本次保存将更新它"
              description={`当前为：${describePlan(autoTarget)}`}
            />
          )}
          <div className="sk-evening-hours-fields">
            <Form.Item name="class_id" label="班级" rules={[{ required: true, message: '请选择班级' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择班级" options={classes.map((item) => ({ label: item.name, value: item.id }))} notFoundContent={<SelectEmptyGuide description="暂无可用班级" path="/classes" actionLabel="去班级管理创建" compact />} />
            </Form.Item>
            <Form.Item name="subject_id" label="科目" rules={[{ required: true, message: '请选择科目' }]}>
              <Select showSearch optionFilterProp="label" placeholder="选择科目" options={subjects.map((item) => ({ label: item.name, value: item.id }))} notFoundContent={<SelectEmptyGuide description="暂无可用科目" path="/subjects" actionLabel="去科目管理创建" compact />} />
            </Form.Item>
          </div>

          <div className="sk-hours-section">
            <span>白天课时</span>
            <span className="sk-hours-section-hint">工作日 + 周末</span>
          </div>
          <div className="walk-hours-input-grid">
            <div className="walk-hours-input-group">
            <Form.Item name="weekday_periods" label="工作日课时" extra="周一至周五合计" rules={[{ required: true, message: '请输入工作日课时' }]}>
              <InputNumber min={0} max={20} step={0.5} size="large" suffix="节" />
            </Form.Item>
            </div>
            <div className="walk-hours-input-group">
            <Form.Item name="saturday_periods" label="周末课时" extra="当前排课范围：周六" rules={[{ required: true, message: '请输入周末课时' }]}>
              <InputNumber min={0} max={10} step={0.5} size="large" suffix="节" />
            </Form.Item>
            </div>
          </div>
          <div className="walk-hours-total" aria-live="polite">
            <div>白天每周合计<small>不含晚自习</small></div>
            <div><strong>{formatPeriods(weekdayPeriods + saturdayPeriods)}</strong><span className="walk-hours-total-unit">节</span></div>
          </div>
          <div className="admin-hours-capacity">
              {daytimeCapacity != null && (
                <span className={daytimeAfterSave > daytimeCapacity ? 'sk-hours-cap-warn' : undefined}>
                  本班 {formatPeriods(daytimeAfterSave)}/{formatPeriods(daytimeCapacity)} 节
                  {daytimeAfterSave > daytimeCapacity ? ' · 超出课位容量' : ' · 白天课位'}
                </span>
              )}
            {daytimeCapacity != null && daytimeCapacity > 0 && (
              <Progress
                size="small"
                showInfo={false}
                percent={Math.min(100, Math.round((daytimeAfterSave / daytimeCapacity) * 100))}
                status={daytimeAfterSave > daytimeCapacity ? 'exception' : 'success'}
              />
            )}
          </div>
          {hasHalfPeriod ? (
            <Form.Item name="week_parity" label="白天隔周" extra="含 0.5 节时需说明隔周方式；不影响晚课。">
              <Select options={[
                { value: 'all', label: '无规定（由规则/求解器安排）' },
                { value: 'odd', label: '单周' },
                { value: 'even', label: '双周' },
              ]} />
            </Form.Item>
          ) : null}

          <div className="sk-hours-section">
            <span>晚自习</span>
            <span className="sk-hours-section-hint">不计入白天课时</span>
          </div>
          <Form.Item name="evening_periods" style={{ marginBottom: eveningPeriods === 0.5 ? 12 : 0 }}>
            <Segmented
              block
              options={[
                { value: 0, label: '不上' },
                { value: 1, label: '每周 1 节' },
                { value: 0.5, label: '隔周 1 节' },
              ]}
            />
          </Form.Item>
          {eveningPeriods === 0.5 && (
            <div className="sk-hours-evening-parity">
              <Radio.Group
                size="small"
                optionType="button"
                buttonStyle="solid"
                options={[
                  { value: 'either', label: '无规定' },
                  { value: 'odd', label: '单周' },
                  { value: 'even', label: '双周' },
                ]}
              />
              <span className="sk-hours-evening-parity-hint">无规定：自动安排单双周</span>
            </div>
          )}
        </Form>
      </Modal>
      <Modal
        title="沿用上学期年级配置"
        open={inheritOpen}
        centered
        onCancel={() => setInheritOpen(false)}
        onOk={() => void inheritFromPreviousTerm()}
        okText="确认沿用"
        cancelText="取消"
        confirmLoading={inheriting}
      >
        <p>将第 1 学期的配置沿用到第 2 学期，范围为当前高一年级的全部班级。</p>
        <p>目标学期对应班级和学科已有配置会被上学期配置替换，其他数据不会删除；班级下拉框只影响查看，不影响沿用范围。</p>
        <p>此操作可以重复执行，不会产生重复数据。</p>
        <p>排课规则是学期级配置，勾选后会作用于第 2 学期全部班级；目标学期独有的规则组会保留。</p>
        <Checkbox.Group
          value={inheritTypes}
          onChange={(values) => setInheritTypes(values as string[])}
          options={[
            { label: '课时方案（工作日、周末、晚课、单双周）', value: 'course_hours' },
            { label: '任教关系（教师、班级、学科、周课时）', value: 'assignments' },
            { label: '排课规则（硬约束、软目标、启用状态）', value: 'rules' },
          ]}
          style={{ display: 'grid', gap: 12 }}
        />
      </Modal>
    </section>
  )
}
