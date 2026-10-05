import { useEffect, useState } from 'react'
import { App, Button, Checkbox, Form, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { schedulingApi } from '@/api'
import type { ClassInfo, CourseHourPlanInfo, EveningParity, SubjectInfo, WeekParity } from '@/types'
import SelectEmptyGuide from '@/components/SelectEmptyGuide'

interface CourseHoursPanelProps {
  classes: ClassInfo[]
  subjects: SubjectInfo[]
  academicYear: string
  term: string
  classId?: number
  onClassChange?: (classId?: number) => void
  classOptions?: Array<{ label: string; value: number }>
  onInherited?: () => Promise<void> | void
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

export default function CourseHoursPanel({
  classes,
  subjects,
  academicYear,
  term,
  classId,
  onClassChange,
  classOptions,
  onInherited,
}: CourseHoursPanelProps) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<CourseHourPlanInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<CourseHourPlanInfo>()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [inheritOpen, setInheritOpen] = useState(false)
  const [inheriting, setInheriting] = useState(false)
  const [inheritTypes, setInheritTypes] = useState(['course_hours', 'assignments'])
  const [form] = Form.useForm<CourseHourFormValues>()
  const weekdayPeriods = Form.useWatch('weekday_periods', form) ?? 0
  const saturdayPeriods = Form.useWatch('saturday_periods', form) ?? 0
  const eveningPeriods = Form.useWatch('evening_periods', form) ?? 0
  const hasHalfPeriod = hasHalfDaytime(weekdayPeriods, saturdayPeriods)

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

  const load = async () => {
    setLoading(true)
    try {
      setRows(await schedulingApi.courseHours({ academic_year: academicYear, term, class_id: classId }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课时方案加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [academicYear, term, classId])

  const close = () => {
    setOpen(false)
    setEditing(undefined)
    form.resetFields()
  }

  const openCreate = () => {
    setEditing(undefined)
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
    const both = Boolean(row.evening_periods_odd && row.evening_periods_even)
    const stored = row.evening_parity
    const eveningParity: EveningParityChoice = stored
      ? stored
      : both
        ? (row.week_parity !== 'all' ? 'either' : 'all')
        : (row.evening_periods_odd && !row.evening_periods_even ? 'odd' : 'even')
    const isHalfEvening = eveningParity === 'either' || eveningParity === 'odd' || eveningParity === 'even'
    form.setFieldsValue({
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
    })
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
      await schedulingApi.saveCourseHour({
        id: editing?.id,
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
      message.success(editing ? '课时方案已更新' : '课时方案已保存')
      close()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '课时方案保存失败')
    } finally {
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
    { title: '周六', dataIndex: 'saturday_periods', key: 'saturday_periods', width: 100, align: 'center', render: (value: number) => `${value} 节` },
    { title: '合计', dataIndex: 'weekly_periods', key: 'weekly_periods', width: 100, align: 'center', render: (value: number) => `${value} 节` },
    { title: '晚课', key: 'evening_periods', width: 170, align: 'center', render: (_, row) => {
      const mode = row.evening_parity
        ?? (row.evening_periods_odd && row.evening_periods_even
          ? (row.week_parity !== 'all' ? 'either' : 'all')
          : (row.evening_periods_odd ? 'odd' : row.evening_periods_even ? 'even' : 'all'))
      if (mode === 'either') return '0.5 节（无规定）'
      if (mode === 'odd') return '0.5 节（单周）'
      if (mode === 'even') return '0.5 节（双周）'
      if (row.evening_periods_odd && row.evening_periods_even) return '1 节（每周）'
      return '0 节'
    } },
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

  return (
    <section className="sk-hours">
      <div className="sk-hours-intro">
        <div>
          <div className="sk-hours-kicker">COURSE LOAD / 课时方案</div>
          <h2>课时管理</h2>
          <p>一条方案对应老师表的一行：工作日和周六属于白天课时，晚课单独维护。白天隔周类型同时作用于工作日与周六，不影响晚课单双周。</p>
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
      <div className="sk-hours-summary">
        <div><strong>{rows.length}</strong><span>条课时方案</span></div>
        <div><strong>{weekdayTotal}</strong><span>工作日课时</span></div>
        <div><strong>{saturdayTotal}</strong><span>周六课时</span></div>
        <div><strong>{daytimeTotal}</strong><span>白天课时合计</span></div>
        <div className="sk-hours-summary-note">当前范围：{classId ? (classes.find((item) => item.id === classId)?.name || '当前班级') : '全部班级'} · {academicYear} · 第 {term} 学期</div>
      </div>
      <Table<CourseHourPlanInfo>
        className="sk-hours-table"
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
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
      <Modal title={editing ? '编辑课时方案' : '新增课时方案'} open={open} centered onCancel={close} onOk={() => form.submit()} okText="保存" cancelText="取消" confirmLoading={saving}>
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="class_id" label="班级" rules={[{ required: true, message: '请选择班级' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择班级" options={classes.map((item) => ({ label: item.name, value: item.id }))} notFoundContent={<SelectEmptyGuide description="暂无可用班级" path="/classes" actionLabel="去班级管理创建" compact />} />
          </Form.Item>
          <Form.Item name="subject_id" label="科目" rules={[{ required: true, message: '请选择科目' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择科目" options={subjects.map((item) => ({ label: item.name, value: item.id }))} notFoundContent={<SelectEmptyGuide description="暂无可用科目" path="/subjects" actionLabel="去科目管理创建" compact />} />
          </Form.Item>
          <Form.Item name="weekday_periods" label="工作日课时" rules={[{ required: true, message: '请输入工作日课时' }]} extra="周一至周五的合计课时。">
            <InputNumber min={0} max={20} step={0.5} addonAfter="节" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="saturday_periods" label="周六课时" rules={[{ required: true, message: '请输入周六课时' }]} extra="没有周六课时就填 0。">
            <InputNumber min={0} max={10} step={0.5} addonAfter="节" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="白天课时合计">
            <InputNumber value={weekdayPeriods + saturdayPeriods} addonAfter="节" disabled style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="week_parity" label="白天隔周类型（工作日 + 周六）" rules={[{ required: true, message: '请选择白天隔周类型' }]} extra={hasHalfPeriod ? '作用于上方的工作日课时和周六课时；0.5 节默认无规定，由对课规则或求解器安排单双周。此项不影响晚课。' : '作用于上方的工作日课时和周六课时；整节白天课按每周安排。此项不影响晚课。'}>
            <Select options={Object.entries(parityLabels).map(([value, label]) => ({
              value,
              label: value === 'all'
                ? (hasHalfPeriod ? '无规定（由规则/求解器安排）' : `${label}（普通课时）`)
                : `${label}（隔周课时）`,
              disabled: hasHalfPeriod ? false : value !== 'all',
            }))} />
          </Form.Item>
          <div className="sk-evening-hours-fields">
            <Form.Item name="evening_periods" label="晚课课时（独立维护）" rules={[{ required: true, message: '请输入晚课课时' }]} extra="只作用于晚自习课位，不计入工作日或周六白天课时；1 = 两周都上，0.5 = 每周只上一节，没有就填 0。">
              <InputNumber min={0} max={1} step={0.5} addonAfter="节" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item
              name="evening_parity"
              label="0.5 晚课单双周安排"
              extra="单周、双周，或无规定由程序安排。物理和历史无规定时，可单物双史，也可单史双物。"
            >
              <Select
                disabled={eveningPeriods !== 0.5}
                placeholder="无规定"
                options={[
                  { value: 'either', label: '无规定' },
                  { value: 'odd', label: '单周' },
                  { value: 'even', label: '双周' },
                ]}
              />
            </Form.Item>
          </div>
          <div className="sk-rule-info-card"><strong>配置范围说明</strong><span>白天隔周类型只控制工作日和周六课时；晚课课时及晚课单双周安排单独控制晚自习。每个晚上只有 1 节：语数外通常填 1，其他科目通常填 0.5，并可选择单周、双周或无规定。</span></div>
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
            { label: '课时方案（工作日、周六、晚课、单双周）', value: 'course_hours' },
            { label: '任教关系（教师、班级、学科、周课时）', value: 'assignments' },
            { label: '排课规则（硬约束、软目标、启用状态）', value: 'rules' },
          ]}
          style={{ display: 'grid', gap: 12 }}
        />
      </Modal>
    </section>
  )
}
