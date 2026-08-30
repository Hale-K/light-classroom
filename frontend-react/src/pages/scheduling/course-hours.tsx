import { useEffect, useState } from 'react'
import { App, Button, Form, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { schedulingApi } from '@/api'
import type { ClassInfo, CourseHourPlanInfo, SubjectInfo, WeekParity } from '@/types'

interface CourseHoursPanelProps {
  classes: ClassInfo[]
  subjects: SubjectInfo[]
  academicYear: string
  term: string
  classId?: number
}

interface CourseHourFormValues {
  class_id: number
  subject_id: number
  weekday_periods: number
  saturday_periods: number
  weekly_periods: number
  week_parity: WeekParity
  evening_periods: number
  evening_parity: WeekParity
}

const parityLabels: Record<WeekParity, string> = { all: '每周', odd: '单周', even: '双周' }

export default function CourseHoursPanel({ classes, subjects, academicYear, term, classId }: CourseHoursPanelProps) {
  const { message } = App.useApp()
  const [rows, setRows] = useState<CourseHourPlanInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<CourseHourPlanInfo>()
  const [form] = Form.useForm<CourseHourFormValues>()
  const weekdayPeriods = Form.useWatch('weekday_periods', form) ?? 0
  const saturdayPeriods = Form.useWatch('saturday_periods', form) ?? 0
  const eveningPeriods = Form.useWatch('evening_periods', form) ?? 0
  const hasHalfPeriod = [weekdayPeriods, saturdayPeriods].some((value) => value % 1 !== 0)

  useEffect(() => {
    const currentParity = form.getFieldValue('week_parity') as WeekParity | undefined
    if (hasHalfPeriod && currentParity === 'all') {
      // 0.5 节表示隔周课时；按学期默认首周为单周，用户仍可手动切换为双周。
      form.setFieldValue('week_parity', 'odd')
    } else if (!hasHalfPeriod && currentParity && currentParity !== 'all') {
      form.setFieldValue('week_parity', 'all')
    }
  }, [form, hasHalfPeriod])

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
    form.setFieldsValue({ class_id: classId, weekday_periods: 4, saturday_periods: 0, weekly_periods: 4, week_parity: 'all', evening_periods: 0, evening_parity: 'all' })
    setOpen(true)
  }

  const openEdit = (row: CourseHourPlanInfo) => {
    setEditing(row)
    form.setFieldsValue({
      class_id: row.class_id,
      subject_id: row.subject_id,
      weekday_periods: row.weekday_periods,
      saturday_periods: row.saturday_periods,
      weekly_periods: row.weekly_periods,
      week_parity: row.week_parity,
      evening_periods: row.evening_periods_odd && row.evening_periods_even ? 1 : (row.evening_periods_odd || row.evening_periods_even ? 0.5 : 0),
      evening_parity: row.evening_periods_odd && !row.evening_periods_even ? 'odd' : (row.evening_periods_even && !row.evening_periods_odd ? 'even' : 'all'),
    })
    setOpen(true)
  }

  const submit = async (values: CourseHourFormValues) => {
    if (values.evening_periods === 0.5 && !['odd', 'even'].includes(values.evening_parity)) {
      message.error('晚课填 0.5 时，请选择单周或双周')
      return
    }
    setSaving(true)
    try {
      const eveningPeriodsOdd = values.evening_periods === 1 || (values.evening_periods === 0.5 && values.evening_parity === 'odd') ? 1 : 0
      const eveningPeriodsEven = values.evening_periods === 1 || (values.evening_periods === 0.5 && values.evening_parity === 'even') ? 1 : 0
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

  const columns: ColumnsType<CourseHourPlanInfo> = [
    { title: '班级', dataIndex: 'class_name', key: 'class_name', width: 180, render: (value) => <strong>{value || '未知班级'}</strong> },
    { title: '科目', dataIndex: 'subject_name', key: 'subject_name', width: 140 },
    { title: '工作日', dataIndex: 'weekday_periods', key: 'weekday_periods', width: 110, align: 'center', render: (value: number) => `${value} 节` },
    { title: '周六', dataIndex: 'saturday_periods', key: 'saturday_periods', width: 100, align: 'center', render: (value: number) => `${value} 节` },
    { title: '合计', dataIndex: 'weekly_periods', key: 'weekly_periods', width: 100, align: 'center', render: (value: number) => `${value} 节` },
    { title: '晚课', key: 'evening_periods', width: 150, align: 'center', render: (_, row) => {
      if (row.evening_periods_odd && row.evening_periods_even) return '1 节（每周）'
      if (row.evening_periods_odd) return '0.5 节（单周）'
      if (row.evening_periods_even) return '0.5 节（双周）'
      return '0 节'
    } },
    { title: '周次', dataIndex: 'week_parity', key: 'week_parity', width: 120, align: 'center', render: (value: WeekParity) => <Tag color={value === 'all' ? 'blue' : 'gold'}>{parityLabels[value]}</Tag> },
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
          <p>一条方案对应老师表的一行：工作日、周六、晚课分别维护；晚课填 0、0.5 或 1，生成时沿用任教关系自动带出坐班老师。</p>
        </div>
        <Space>
          <Button onClick={() => void load()} loading={loading}>刷新</Button>
          <Button type="primary" onClick={openCreate}>新增课时</Button>
        </Space>
      </div>
      <div className="sk-hours-summary">
        <div><strong>{rows.length}</strong><span>条课时方案</span></div>
        <div><strong>{weekdayTotal}</strong><span>工作日课时</span></div>
        <div><strong>{saturdayTotal}</strong><span>周六课时</span></div>
        <div><strong>{daytimeTotal}</strong><span>排课课时</span></div>
        <div className="sk-hours-summary-note">当前范围：{classId ? (classes.find((item) => item.id === classId)?.name || '当前班级') : '全部班级'} · {academicYear} · 第 {term} 学期</div>
      </div>
      <Table<CourseHourPlanInfo>
        className="sk-hours-table"
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 12, showSizeChanger: false }}
        locale={{ emptyText: '暂无课时方案，请先新增班级课程课时' }}
      />
      <Modal title={editing ? '编辑课时方案' : '新增课时方案'} open={open} centered onCancel={close} onOk={() => form.submit()} okText="保存" cancelText="取消" confirmLoading={saving}>
        <Form form={form} layout="vertical" onFinish={submit}>
          <Form.Item name="class_id" label="班级" rules={[{ required: true, message: '请选择班级' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择班级" options={classes.map((item) => ({ label: item.name, value: item.id }))} />
          </Form.Item>
          <Form.Item name="subject_id" label="科目" rules={[{ required: true, message: '请选择科目' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择科目" options={subjects.map((item) => ({ label: item.name, value: item.id }))} />
          </Form.Item>
          <Form.Item name="weekday_periods" label="工作日课时" rules={[{ required: true, message: '请输入工作日课时' }]} extra="周一至周五的合计课时。">
            <InputNumber min={0} max={20} step={0.5} addonAfter="节" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="saturday_periods" label="周六课时" rules={[{ required: true, message: '请输入周六课时' }]} extra="没有周六课时就填 0。">
            <InputNumber min={0} max={10} step={0.5} addonAfter="节" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="周课时合计">
            <InputNumber value={weekdayPeriods + saturdayPeriods} addonAfter="节" disabled style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="week_parity" label="隔周类型" rules={[{ required: true, message: '请选择隔周类型' }]} extra={hasHalfPeriod ? '包含 0.5 节时，选择这部分安排在单周还是双周。' : '整节课按每周安排。'}>
            <Select options={Object.entries(parityLabels).map(([value, label]) => ({
              value,
              label: value === 'all' ? `${label}（普通课时）` : `${label}（隔周课时）`,
              disabled: hasHalfPeriod ? value === 'all' : value !== 'all',
            }))} />
          </Form.Item>
          <div className="sk-evening-hours-fields">
            <Form.Item name="evening_periods" label="晚课" rules={[{ required: true, message: '请输入晚课课时' }]} extra="1 = 两周都上；0.5 = 单周或双周上一节；没有就填 0。">
              <InputNumber min={0} max={1} step={0.5} addonAfter="节" style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="evening_parity" label="0.5 晚课安排" rules={[{ required: true, message: '请选择单周或双周' }]} extra="只有晚课填 0.5 时需要选择。">
              <Select disabled={eveningPeriods !== 0.5} options={[{ value: 'odd', label: '单周' }, { value: 'even', label: '双周' }, { value: 'all', label: '两周都上' }]} />
            </Form.Item>
          </div>
          <div className="sk-rule-info-card"><strong>晚课</strong><span>每个晚上只有 1 节。两门科目各填 0.5 并分别选择单周、双周，就会形成 A｜B；同一门科目填 1，就会形成 B｜B。老师从对应任教关系带出。</span></div>
        </Form>
      </Modal>
    </section>
  )
}
