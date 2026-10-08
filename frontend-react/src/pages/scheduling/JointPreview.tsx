import { useMemo, useState, type ReactNode } from 'react'
import { Alert, Empty, Select, Table, Tabs, Tag } from 'antd'
import { gaokaoApi } from '@/api'
import { selectPreviewLessons, filterPreviewStudents, primaryClassLabel, summarizeTeacherWorkload, type PreviewView } from './joint-preview'
import './joint-preview.css'

type Preview = Awaited<ReturnType<typeof gaokaoApi.previewRegroupPlan>>
const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function JointPreview({ preview, gradeControl }: { preview: Preview; gradeControl: ReactNode }) {
  const [view, setView] = useState<PreviewView>('student')
  const [activeTab, setActiveTab] = useState<PreviewView | 'teachers'>('student')
  const [selected, setSelected] = useState<Partial<Record<PreviewView, number>>>({})
  const [classId, setClassId] = useState<number>()
  const [query, setQuery] = useState('')
  const [workloadSubject, setWorkloadSubject] = useState<string>()
  // An old running backend must not be mistaken for a complete timetable preview.
  if (!preview.lessons || !preview.students || !preview.slots) return <Alert type="warning" showIcon
    message="当前服务未返回候选课表，请更新后端并重新预览。" />
  const filtered = filterPreviewStudents(preview.students, classId, query)
  const workloadDataComplete = preview.lessons.every(lesson => Number.isInteger(lesson.teacher_id) && lesson.teacher_id > 0)
  const adminOptions = preview.admin_classes.map(c => ({ value: c.id,
    label: `${c.name} · ${primaryClassLabel(preview.students, c.id)}` }))
  const options = view === 'student' ? filtered.map(s => ({ value: s.id,
    label: `${s.name} · ${s.class_name} · ${[s.primary_subject_name, ...(s.secondary_subject_names ?? [])].filter(Boolean).join('＋') || '选科未提供'}` }))
    : view === 'admin' ? adminOptions : preview.classes.map(c => ({ value: c.id, label: c.name }))
  const id = options.some(o => o.value === selected[view]) ? selected[view] : options[0]?.value
  const student = view === 'student' ? preview.students.find(s => s.id === id) : undefined
  const lessons = selectPreviewLessons(preview.lessons, view, id, preview.students)
  const workloadSubjects = [...new Set(preview.lessons.map(lesson => lesson.subject_name))]
    .sort((a, b) => a.localeCompare(b, 'zh-CN'))
  const teacherLoads = useMemo(() => summarizeTeacherWorkload(preview.lessons, workloadSubject), [preview.lessons, workloadSubject])
  const workloadSpread = teacherLoads.length
    ? teacherLoads[0].total - teacherLoads[teacherLoads.length - 1].total
    : 0
  const workloadAverage = teacherLoads.length
    ? teacherLoads.reduce((sum, row) => sum + row.total, 0) / teacherLoads.length
    : 0
  const workloadSummary = workloadSubject
    ? `${workloadSubject}　${teacherLoads.length} 位教师　均值 ${workloadAverage.toFixed(1)}　最高 ${teacherLoads[0]?.total ?? 0}　最低 ${teacherLoads.at(-1)?.total ?? 0}　差 ${workloadSpread}`
    : '教师课时（按学科）'
  const days = [...new Set(preview.slots.map(s => s.weekday))].sort((a, b) => a - b)
  const periods = [...new Set(preview.slots.map(s => s.period))].sort((a, b) => a - b)
  const content = <>
    <div className="joint-preview-toolbar">
      <div className="joint-preview-filters">
        {gradeControl}
        {view === 'student' && <label>行政班<Select aria-label="筛选行政班" allowClear showSearch
          optionFilterProp="label" placeholder="全部行政班" value={classId} options={adminOptions}
          onChange={value => { setClassId(value); setQuery(''); setSelected(current => ({ ...current, student: undefined })) }} /></label>}
        <label>{view === 'student' ? '学生姓名' : view === 'admin' ? '行政班' : '教学班'}
          <Select aria-label={view === 'student' ? '选择学生预览' : view === 'admin' ? '选择行政班预览' : '选择教学班预览'}
            showSearch optionFilterProp="label" options={options} value={id}
            placeholder={view === 'student' ? '输入姓名查找学生' : '请选择班级'}
            filterOption={view === 'student' ? false : undefined}
            onSearch={view === 'student' ? setQuery : undefined}
            notFoundContent="没有匹配的学生或班级"
            onChange={value => { setSelected(current => ({ ...current, [view]: value })); setQuery('') }} />
        </label>
      </div>
      <span><Tag color="blue">行政课</Tag><Tag color="orange">走班课</Tag>共 {lessons.length} 节</span>
    </div>
    {view === 'student' && <div className="joint-student-context" aria-live="polite">
      {student ? <><strong>{student.name}</strong><span>{student.class_name}</span>
        <Tag color={student.primary_subject_name === '历史' ? 'orange' : 'blue'}>
          {student.primary_subject_name ? `${student.primary_subject_name}方向` : '首选科目未提供'}</Tag>
        <span>选科：{[student.primary_subject_name, ...(student.secondary_subject_names ?? [])].filter(Boolean).join('＋') || '未提供'}</span>
      </> : <span>当前班级及姓名条件下没有匹配的学生</span>}
      <span>匹配 {filtered.length} 人</span>
    </div>}
    <p className="joint-preview-note">{view === 'student' ? '合并展示该学生本次方案中的行政课与走班课。'
      : view === 'admin' ? '仅展示该行政班的公共课；空白时段可能安排了走班课，请在学生完整课表中查看。'
        : '仅展示该教学班的课程安排。'} 所有内容均为预览，尚未保存。</p>
    {!options.length ? <Empty description="没有匹配结果，请清空姓名搜索或切换行政班" /> :
      <div className="joint-preview-grid" tabIndex={0} role="region" aria-label="候选周课表，可横向滚动">
        <table><caption className="sr-only">{options.find(o => o.value === id)?.label} · 本次候选课表</caption>
          <thead><tr><th scope="col">节次</th>{days.map(d => <th scope="col" key={d}>{dayNames[d - 1]}</th>)}</tr></thead>
          <tbody>{periods.map(p => <tr key={p}><th scope="row">第 {p} 节</th>{days.map(d => {
            const enabled = preview.slots.some(s => s.weekday === d && s.period === p)
            const items = lessons.filter(r => r.weekday === d && r.period === p)
            return <td key={d}>{items.length ? items.map((r, i) => <div className={`joint-lesson ${r.kind}`} key={i}>
              <div><strong>{r.subject_name}</strong><span>{r.kind === 'admin' ? '行政' : '走班'}</span></div>
              <small>{r.teacher_name} · {r.room || '未指定教室'}</small>
              {r.kind === 'walk' && <small>{r.class_name}</small>}
            </div>) : <span className="joint-empty">{enabled ? '—' : '未开放'}</span>}</td>
          })}</tr>)}</tbody></table>
      </div>}
  </>
  return <Tabs activeKey={activeTab} onChange={key => {
    const next = key as PreviewView | 'teachers'
    setActiveTab(next)
    if (next !== 'teachers') setView(next)
  }} items={[
    { key: 'student', label: '学生完整课表', children: content },
    { key: 'admin', label: '行政班课表', children: content },
    { key: 'walk', label: '教学班课表', children: content },
    { key: 'teachers', label: '教师工作量', children: !workloadDataComplete
      ? <Alert type="warning" showIcon message="教师信息不完整，无法统计课时。" />
      : <>
      <div className="joint-workload-summary" role="status">{workloadSummary}</div>
      <Select aria-label="筛选教师工作量学科" value={workloadSubject} allowClear placeholder="全部学科"
        style={{ width: 200, marginTop: 12 }} options={workloadSubjects.map(subject => ({ value: subject, label: subject }))}
        onChange={setWorkloadSubject} />
      <Table size="small" rowKey={row => `${row.teacher_id}-${row.subject_name}`} style={{ marginTop: 12 }} dataSource={teacherLoads}
        pagination={false} locale={{ emptyText: '本次方案暂无教师课时' }} columns={[
          ...(!workloadSubject ? [{ title: '学科', dataIndex: 'subject_name' }] : []),
          { title: '教师', dataIndex: 'teacher_name' },
          { title: '行政课', dataIndex: 'admin', render: (value: number) => value },
          { title: '走班课', dataIndex: 'walk', render: (value: number) => value },
          { title: '该科合计', dataIndex: 'total', render: (value: number) => <strong>{value}</strong>, sorter: (a: typeof teacherLoads[number], b: typeof teacherLoads[number]) => a.total - b.total },
          ...(!workloadSubject ? [{ title: '学科总课时', dataIndex: 'subject_total', render: (value: number) => value, sorter: (a: typeof teacherLoads[number], b: typeof teacherLoads[number]) => a.subject_total - b.subject_total }] : []),
          { title: '较同科均值', dataIndex: 'difference', render: (value: number, row: typeof teacherLoads[number]) =>
            teacherLoads.filter(item => item.subject_name === row.subject_name).length < 2 ? '—'
              : <Tag color={value > 0 ? 'gold' : value < 0 ? 'blue' : undefined}>{value > 0 ? '+' : ''}{value.toFixed(1)}</Tag> },
        ]} />
    </> },
    { key: 'groups', label: '分班结果', children: <Table size="small" rowKey="id" dataSource={preview.classes}
      pagination={{ pageSize: 8, showSizeChanger: false }} columns={[
        { title: '教学班', dataIndex: 'name' }, { title: '科目', dataIndex: 'subject_name' },
        { title: '人数', dataIndex: 'student_count' }, { title: '班额上限', dataIndex: 'capacity' },
      ]} /> },
  ]} />
}
