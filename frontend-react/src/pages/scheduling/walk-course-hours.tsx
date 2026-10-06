import { useEffect, useRef, useState } from 'react'
import { Alert, App, Button, Form, InputNumber, Modal, Select, Space, Table, Tag } from 'antd'
import { Link } from 'react-router-dom'
import { gaokaoApi, orgApi } from '@/api'
import type { GaokaoOverview, WalkTeachingClass } from '@/api'
import type { Grade, SubjectInfo } from '@/types'

type SubjectRow = {
  id: number; name: string; students: number; recommended: number
  classes: WalkTeachingClass[]; planned?: number
}

export default function WalkCourseHoursPanel({ academicYear, term, subjects, initialGradeId }: {
  academicYear: string; term: string; subjects: SubjectInfo[]; initialGradeId?: number
}) {
  const { message } = App.useApp()
  const [grades, setGrades] = useState<Grade[]>([])
  const [gradeId, setGradeId] = useState<number | undefined>(initialGradeId)
  const [overview, setOverview] = useState<GaokaoOverview>()
  const [classes, setClasses] = useState<WalkTeachingClass[]>([])
  const [plans, setPlans] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [choosingSubject, setChoosingSubject] = useState(false)
  const [editing, setEditing] = useState<{ subject: SubjectRow; teachingClass?: WalkTeachingClass }>()
  const [form] = Form.useForm<{ weekly_periods: number }>()
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
        gaokaoApi.overview(scope), gaokaoApi.teachingClasses(scope), gaokaoApi.teachingSubjectHours(scope),
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
    const unique = [...new Set(subject.classes.map((item) => item.weekly_periods))]
    form.setFieldsValue({ weekly_periods: teachingClass?.weekly_periods ?? subject.planned ?? (unique.length === 1 ? unique[0] : undefined) })
  }

  const save = async ({ weekly_periods }: { weekly_periods: number }) => {
    if (!gradeId || !editing) return
    setSaving(true)
    try {
      const scope = { grade_id: gradeId, academic_year: academicYear, term, weekly_periods }
      const result = editing.teachingClass
        ? await gaokaoApi.updateTeachingClassHours(editing.teachingClass.id, scope)
        : await gaokaoApi.updateTeachingSubjectHours({ ...scope, subject_id: editing.subject.id })
      message.success(result.cleared_schedule_count ? `课时已保存，已清除 ${result.cleared_schedule_count} 条受影响排课，请重新排课` : '走班课时已保存')
      setEditing(undefined)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '课时保存失败') }
    finally { setSaving(false) }
  }

  return <section className="sk-hours">
    <div className="sk-hours-intro">
      <div><div className="sk-hours-kicker">走班课时方案</div><h2>按科目设置教学班课时</h2>
        <p>每周课时指每名学生在该教学班每周上课的节数。可先配置科目课时，生成教学班时自动带入；教师与教室在后续步骤安排。</p></div>
      <Space wrap>
        <Select aria-label="走班课时年级" style={{ width: 240 }} value={gradeId} disabled={saving} placeholder="选择年级"
          onChange={setGradeId} options={grades.map((item) => ({ value: item.id, label: item.name }))} />
        <Button loading={loading} onClick={() => void load()}>刷新</Button>
        <Button type="primary" disabled={!gradeId || saving} onClick={() => setChoosingSubject(true)}>新增走班科目课时</Button>
      </Space>
    </div>
    <div className="sk-hours-summary">
      <div><strong>{data.length}</strong><span>门走班科目</span></div>
      <div><strong>{classes.length}</strong><span>个教学班</span></div>
      <div><strong>{classes.reduce((sum, item) => sum + item.weekly_periods, 0)}</strong><span>教学班周课时合计</span></div>
      <div className="sk-hours-summary-note">{grades.find((item) => item.id === gradeId)?.name} · {academicYear} · 第 {term} 学期</div>
    </div>
    <Table<SubjectRow> rowKey="id" loading={loading} dataSource={data} pagination={false}
      locale={{ emptyText: '暂无走班科目，可先新增科目课时，或确认选科后生成教学班。' }} columns={[
        { title: '科目', dataIndex: 'name', render: (value) => <strong>{value}</strong> },
        { title: '选科人数', render: (_, row) => `${row.students || row.classes.reduce((sum, item) => sum + item.student_count, 0)} 人` },
        { title: '教学班数', render: (_, row) => row.classes.length ? `${row.classes.length} 个` : <Tag>未生成{row.recommended ? `（建议 ${row.recommended} 个）` : ''}</Tag> },
        { title: '科目周课时', render: (_, row) => row.planned ? `${row.planned} 节 / 班` : '未设置' },
        { title: '教学班实际周课时', render: (_, row) => {
          const values = [...new Set(row.classes.map((item) => item.weekly_periods))]
          return values.length === 1 ? `${values[0]} 节 / 班` : values.length > 1 ? <Tag color="orange">各班不同，展开查看</Tag> : '生成后带入'
        } },
        { title: '操作', render: (_, row) => <Button type="link" onClick={() => open(row)}>设置课时</Button> },
      ]} expandable={{ rowExpandable: (row) => row.classes.length > 0, expandedRowRender: (row) =>
        <Table<WalkTeachingClass> rowKey="id" dataSource={row.classes} size="small" pagination={false} columns={[
          { title: '教学班', dataIndex: 'name' }, { title: '人数', dataIndex: 'student_count' },
          { title: '周课时', dataIndex: 'weekly_periods', render: (value) => `${value} 节` },
          { title: '课时来源', render: (_, item) => <Tag color={item.hours_overridden ? 'orange' : 'blue'}>{item.hours_overridden ? '单班调整' : '教学班课时'}</Tag> },
          { title: '操作', render: (_, item) => <Button type="link" onClick={() => open(row, item)}>单独调整</Button> },
        ]} /> }} />
    <p style={{ marginTop: 16, color: 'var(--text-3)' }}>尚未组建教学班？<Link to="/gaokao">前往学生选课确认选科并生成教学班</Link>。走班科目请勿重复添加到行政班课时。</p>
    <Modal title="选择走班科目" open={choosingSubject} centered footer={null} onCancel={() => setChoosingSubject(false)} destroyOnHidden>
      <Select aria-label="走班科目" style={{ width: '100%' }} placeholder="选择需要走班授课的科目"
        options={subjects.filter((item) => item.course_type !== 'activity').map((item) => ({ value: item.id, label: item.name }))}
        onChange={(id) => {
          const item = subjects.find((subject) => subject.id === id)!
          setChoosingSubject(false)
          open(rows.get(id) || { id, name: item.name, students: 0, recommended: 0, classes: [] })
        }} />
    </Modal>
    <Modal title={editing?.teachingClass ? `调整 ${editing.teachingClass.name} 课时` : `设置 ${editing?.subject.name || ''} 走班课时`}
      open={Boolean(editing)} centered onCancel={() => { if (!saving) setEditing(undefined) }}
      onOk={() => form.submit()} confirmLoading={saving} okText="保存" cancelText="取消" destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={save}>
        <Form.Item name="weekly_periods" label="每个教学班每周课时" rules={[{ required: true, message: '请输入每周课时' }, { type: 'integer', min: 1, max: 12, message: '请输入 1 到 12 的整数' }]}>
          <InputNumber min={1} max={12} precision={0} addonAfter="节" style={{ width: '100%' }} />
        </Form.Item>
        <Alert type="info" showIcon message={editing?.teachingClass ? '仅修改这个教学班，科目默认课时保持不变。' : '保存为该科目默认课时，并同步到本年级本学期的所有该科教学班。'} />
        {Boolean(editing?.subject.classes.length) && <Alert style={{ marginTop: 12 }} type="warning" showIcon message="课时发生变化时，会清除受影响教学班的已有走班课表，需重新排课。" />}
      </Form>
    </Modal>
  </section>
}
