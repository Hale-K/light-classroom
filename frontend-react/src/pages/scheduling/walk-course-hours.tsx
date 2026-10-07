import { useEffect, useRef, useState } from 'react'
import { App, Button, Form, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import { Link } from 'react-router-dom'
import { gaokaoApi, orgApi } from '@/api'
import type { GaokaoOverview, WalkTeachingClass } from '@/api'
import type { Grade, SubjectInfo } from '@/types'
import './walk-course-hours.css'

type HourPlan = { weekly_periods: number; weekday_periods: number | null; weekend_periods: number | null }
type SplitHours = { weekday_periods: number; weekend_periods: number }
type SubjectRow = {
  id: number; name: string; students: number; recommended: number
  classes: WalkTeachingClass[]; planned?: HourPlan
}

export default function WalkCourseHoursPanel({ academicYear, term, subjects, initialGradeId }: {
  academicYear: string; term: string; subjects: SubjectInfo[]; initialGradeId?: number
}) {
  const { message } = App.useApp()
  const [grades, setGrades] = useState<Grade[]>([])
  const [gradeId, setGradeId] = useState<number | undefined>(initialGradeId)
  const [overview, setOverview] = useState<GaokaoOverview>()
  const [classes, setClasses] = useState<WalkTeachingClass[]>([])
  const [plans, setPlans] = useState<Record<string, HourPlan>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [choosingSubject, setChoosingSubject] = useState(false)
  const [editing, setEditing] = useState<{ subject: SubjectRow; teachingClass?: WalkTeachingClass }>()
  const [form] = Form.useForm<SplitHours>()
  const weekdayHours = Form.useWatch('weekday_periods', form)
  const weekendHours = Form.useWatch('weekend_periods', form)
  const requestId = useRef(0)

  useEffect(() => {
    let active = true
    orgApi.grades().then((items) => {
      if (!active) return
      setGrades(items)
      setGradeId((previous) => items.some((item) => item.id === previous) ? previous : items[0]?.id)
    }).catch((error) => { if (active) message.error(error.message || '年级加载失败') })
    return () => { active = false }
  }, [message])

  const load = async () => {
    const version = ++requestId.current
    if (!gradeId || !academicYear) return
    setLoading(true)
    try {
      const scope = { grade_id: gradeId, academic_year: academicYear, term }
      const [nextOverview, nextClasses, nextPlans] = await Promise.all([
        gaokaoApi.overview(scope), gaokaoApi.teachingClasses(scope), gaokaoApi.teachingSubjectHourDetails(scope),
      ])
      if (version !== requestId.current) return
      setOverview(nextOverview); setClasses(nextClasses); setPlans(nextPlans)
    } catch (error) {
      if (version === requestId.current) message.error(error instanceof Error ? error.message : '走班课时加载失败')
    } finally { if (version === requestId.current) setLoading(false) }
  }

  useEffect(() => {
    setOverview(undefined); setClasses([]); setPlans({}); setEditing(undefined); setChoosingSubject(false)
    void load()
    return () => { requestId.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradeId, academicYear, term])

  const rows = new Map<number, SubjectRow>()
  for (const item of overview?.subject_demand ?? []) {
    if (item.delivery_mode === 'teaching_class') rows.set(item.subject_id, {
      id: item.subject_id, name: item.subject_name, students: item.walk_student_count,
      recommended: item.recommended_class_count, classes: [], planned: plans[item.subject_id],
    })
  }
  for (const item of classes) {
    if (!rows.has(item.subject_id)) rows.set(item.subject_id, {
      id: item.subject_id, name: item.subject_name, students: 0, recommended: 0,
      classes: [], planned: plans[item.subject_id],
    })
    rows.get(item.subject_id)!.classes.push(item)
  }
  for (const [key, periods] of Object.entries(plans)) {
    const id = Number(key)
    if (!rows.has(id)) rows.set(id, { id, name: subjects.find((item) => item.id === id)?.name || '未知科目',
      students: 0, recommended: 0, classes: [], planned: periods })
  }
  const data = [...rows.values()]

  const open = (subject: SubjectRow, teachingClass?: WalkTeachingClass) => {
    setEditing({ subject, teachingClass })
    const unique = [...new Set(subject.classes.map((item) => `${item.weekday_periods}/${item.weekend_periods}/${item.weekly_periods}`))]
    const source = teachingClass ?? subject.planned ?? (unique.length === 1 ? subject.classes[0] : undefined)
    // Legacy totals are not an inferred weekday/weekend distribution.
    form.resetFields()
    form.setFieldsValue({ weekday_periods: source?.weekday_periods ?? undefined,
      weekend_periods: source?.weekend_periods ?? undefined })
  }

  const save = async ({ weekday_periods, weekend_periods }: SplitHours) => {
    if (!gradeId || !editing) return
    setSaving(true)
    try {
      const scope = { grade_id: gradeId, academic_year: academicYear, term, weekday_periods, weekend_periods }
      const result = editing.teachingClass
        ? await gaokaoApi.updateTeachingClassHours(editing.teachingClass.id, scope)
        : await gaokaoApi.updateTeachingSubjectHours({ ...scope, subject_id: editing.subject.id })
      message.success(result.cleared_schedule_count ? `课时已保存，已清除 ${result.cleared_schedule_count} 条受影响排课，请重新排课` : '走班课时已保存')
      setEditing(undefined)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '课时保存失败') }
    finally { setSaving(false) }
  }

  const originalHours = editing?.teachingClass ?? editing?.subject.planned
  return <section className="sk-hours walk-hours">
    <div className="sk-hours-intro">
      <div><h2>走班课时</h2><p>按科目设置，教学班自动带入。</p></div>
      <Space wrap className="walk-hours-toolbar">
        <Select aria-label="走班课时年级" className="walk-hours-grade" value={gradeId} disabled={saving} placeholder="选择年级"
          onChange={setGradeId} options={grades.map((item) => ({ value: item.id, label: item.name }))} />
        <Button loading={loading} onClick={() => void load()}>刷新</Button>
        <Button type="primary" disabled={!gradeId || saving} onClick={() => setChoosingSubject(true)}>新增科目</Button>
      </Space>
    </div>
    <div className="walk-hours-meta">
      <span><strong>{data.length}</strong> 门科目</span>
      <span><strong>{classes.length}</strong> 个教学班</span>
      <span className="walk-hours-term">{academicYear} · 第 {term} 学期</span>
    </div>
    <div className="walk-hours-table-wrap">
    <div className="walk-hours-table-heading"><h3>科目课时</h3><span>单位：节 / 教学班</span></div>
    <Table<SubjectRow> rowKey="id" loading={loading} dataSource={data} pagination={false} scroll={{ x: 780 }}
      locale={{ emptyText: '暂无走班科目，可先新增科目课时，或确认选科后生成教学班。' }} columns={[
        { title: '科目', dataIndex: 'name', render: (value) => <strong>{value}</strong> },
        { title: '选科人数', render: (_, row) => `${row.students || row.classes.reduce((sum, item) => sum + item.student_count, 0)} 人` },
        { title: '教学班数', render: (_, row) => row.classes.length ? `${row.classes.length} 个` : <Tag>未生成{row.recommended ? `（建议 ${row.recommended} 个）` : ''}</Tag> },
        { title: '工作日', align: 'center', render: (_, row) => row.planned?.weekday_periods != null ? <span className="walk-hours-number">{row.planned.weekday_periods}</span> : <span className="walk-hours-muted">{row.planned ? '未拆分' : '未设置'}</span> },
        { title: '周末', align: 'center', render: (_, row) => row.planned?.weekend_periods != null ? <span className="walk-hours-number">{row.planned.weekend_periods}</span> : <span className="walk-hours-muted">{row.planned ? '未拆分' : '未设置'}</span> },
        { title: '每周合计', align: 'center', render: (_, row) => row.planned ? <strong className="walk-hours-total-number">{row.planned.weekly_periods}</strong> : <span className="walk-hours-muted">未设置</span> },
        { title: '操作', align: 'right', render: (_, row) => <Button onClick={() => open(row)}>设置课时</Button> },
      ]} expandable={{ rowExpandable: (row) => row.classes.length > 0, expandedRowRender: (row) =>
        <Table<WalkTeachingClass> rowKey="id" dataSource={row.classes} size="small" pagination={false} columns={[
          { title: '教学班', dataIndex: 'name' }, { title: '人数', dataIndex: 'student_count' },
          { title: '工作日', dataIndex: 'weekday_periods', render: (value) => value == null ? '未拆分' : `${value} 节` },
          { title: '周末', dataIndex: 'weekend_periods', render: (value) => value == null ? '未拆分' : `${value} 节` },
          { title: '每周合计', dataIndex: 'weekly_periods', render: (value) => `${value} 节` },
          { title: '课时来源', render: (_, item) => <Tag color={item.hours_overridden ? 'orange' : 'blue'}>{item.hours_overridden ? '单班调整' : '教学班课时'}</Tag> },
          { title: '操作', render: (_, item) => <Button type="link" onClick={() => open(row, item)}>单独调整</Button> },
        ]} /> }} />
    </div>
    <div className="walk-hours-footnote"><span>展开科目，可单独调整教学班。</span><Link to="/gaokao">前往学生选课</Link></div>
    <Modal title="选择走班科目" open={choosingSubject} centered footer={null} onCancel={() => setChoosingSubject(false)} destroyOnHidden>
      <Select aria-label="走班科目" style={{ width: '100%' }} placeholder="选择需要走班授课的科目"
        options={subjects.filter((item) => item.course_type !== 'activity').map((item) => ({ value: item.id, label: item.name }))}
        onChange={(id) => {
          const item = subjects.find((subject) => subject.id === id)!
          setChoosingSubject(false)
          open(rows.get(id) || { id, name: item.name, students: 0, recommended: 0, classes: [] })
        }} />
    </Modal>
    <Modal title={editing?.teachingClass ? '调整教学班课时' : '设置走班课时'} className="walk-hours-modal" width={560}
      open={Boolean(editing)} centered onCancel={() => { if (!saving) setEditing(undefined) }}
      onOk={() => form.submit()} confirmLoading={saving} okText="保存课时" cancelText="取消" cancelButtonProps={{ disabled: saving }} maskClosable={!saving} keyboard={!saving} closable={!saving} destroyOnHidden>
      <div className="walk-hours-modal-context"><strong>{editing?.teachingClass?.name ?? editing?.subject.name}</strong><span>{grades.find((item) => item.id === gradeId)?.name} · 第 {term} 学期</span></div>
      {originalHours?.weekday_periods == null && originalHours && <p className="walk-hours-legacy">原每周 {originalHours.weekly_periods} 节，请确认分配。</p>}
      <Form form={form} layout="vertical" onFinish={save} requiredMark={false} disabled={saving}>
        <div className="walk-hours-input-grid">
          <div className="walk-hours-input-group"><Form.Item name="weekday_periods" label="工作日课时" extra="周一至周五" rules={[{ required: true, message: '请输入工作日课时' }, { type: 'integer', min: 0, max: 12, message: '请输入0到12的整数' }]}>
            <InputNumber min={0} max={12} precision={0} size="large" suffix="节" placeholder="填写课时" />
          </Form.Item></div>
          <div className="walk-hours-input-group"><Form.Item name="weekend_periods" label="周末课时" extra="周六、周日，无课填0" dependencies={['weekday_periods']} rules={[{ required: true, message: '请输入周末课时，无课填0' }, { type: 'integer', min: 0, max: 12, message: '请输入0到12的整数' },
            { validator: async (_, value) => { const work = form.getFieldValue('weekday_periods'); if (work != null && value != null && (work + value < 1 || work + value > 12)) throw new Error('每周合计须为1到12节') } }]}>
            <InputNumber min={0} max={12} precision={0} size="large" suffix="节" placeholder="填写课时" />
          </Form.Item></div>
        </div>
        <div className="walk-hours-total" role="status" aria-live="polite"><span>每周合计<small>工作日 + 周末</small></span><span><strong>{weekdayHours != null && weekendHours != null ? weekdayHours + weekendHours : '—'}</strong><span className="walk-hours-total-unit">节 / 班</span></span></div>
        <p className="walk-hours-save-note">{editing?.teachingClass ? '仅调整此教学班。' : editing?.subject.classes.length ? `同步到 ${editing.subject.classes.length} 个同科教学班。` : '生成教学班时自动带入。'}{Boolean(editing?.subject.classes.length) && '课时变更后需重新排课。'}</p>
      </Form>
    </Modal>
  </section>
}
