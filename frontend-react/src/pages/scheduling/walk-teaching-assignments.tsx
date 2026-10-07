import { useEffect, useState } from 'react'
import { Alert, App, Button, Modal, Select, Space, Table, Tag } from 'antd'
import { gaokaoApi, orgApi } from '@/api'
import type { WalkTeachingClass } from '@/api'
import type { Grade } from '@/types'
import { filterWalkAssignments } from './walk-assignment-filter'

export default function WalkTeachingAssignments({ academicYear, term, initialGradeId }: {
  academicYear: string; term: string; initialGradeId?: number
}) {
  const { message } = App.useApp()
  const [grades, setGrades] = useState<Grade[]>([])
  const [gradeId, setGradeId] = useState(initialGradeId)
  const [classes, setClasses] = useState<WalkTeachingClass[]>([])
  const [teachers, setTeachers] = useState<Awaited<ReturnType<typeof gaokaoApi.teachingClassTeachers>>>([])
  const [subjectId, setSubjectId] = useState<number>()
  const [filterTeacherId, setFilterTeacherId] = useState<number>()
  const [page, setPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([])
  const [editing, setEditing] = useState<WalkTeachingClass[]>([])
  const [teacherId, setTeacherId] = useState<number>()
  const [removing, setRemoving] = useState(false)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let active = true
    orgApi.grades().then((data) => {
      if (active) { setGrades(data); setGradeId((id) => data.some((grade) => grade.id === id) ? id : data[0]?.id) }
    }).catch((e) => { if (active) setError(e.message || '年级加载失败') })
    return () => { active = false }
  }, [])
  useEffect(() => { if (initialGradeId) setGradeId(initialGradeId) }, [initialGradeId])
  useEffect(() => {
    let active = true
    setClasses([]); setTeachers([]); setSelectedIds([]); setEditing([]); setError(''); setSubjectId(undefined); setFilterTeacherId(undefined); setPage(1)
    if (!gradeId) return
    setLoading(true)
    Promise.all([gaokaoApi.teachingClasses({ grade_id: gradeId, academic_year: academicYear, term }),
      gaokaoApi.teachingClassTeachers({ academic_year: academicYear, term })])
      .then(([items, options]) => { if (active) { setClasses(items); setTeachers(options) } })
      .catch((e) => { if (active) setError(e.message || '加载失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [gradeId, academicYear, term, revision])
  const edit = (items: WalkTeachingClass[], remove = false) => {
    if (!items.length) return
    if (!remove && new Set(items.map((item) => item.subject_id)).size !== 1) { message.warning('批量安排请选择同一科目的教学班'); return }
    setEditing(items); setRemoving(remove); setTeacherId(items.length === 1 ? items[0].teacher_id ?? undefined : undefined)
  }
  const save = async () => {
    if (!gradeId || (!removing && !teacherId)) return
    setSaving(true)
    try {
      const result = await gaokaoApi.assignTeachingClassTeachers({ grade_id: gradeId, academic_year: academicYear, term,
        assignments: editing.map((item) => ({ teaching_class_id: item.id, teacher_id: removing ? null : teacherId!, expected_teacher_id: item.teacher_id })) })
      message.success(`已更新 ${result.updated} 个教学班`); setEditing([]); setRevision((value) => value + 1)
    } catch (e) { message.error(e instanceof Error ? e.message : '保存失败，请刷新后重试') }
    finally { setSaving(false) }
  }
  const teacher = teachers.find((item) => item.id === teacherId)
  const visibleClasses = filterWalkAssignments(classes, subjectId, filterTeacherId)
  const filterTeacherOptions = Array.from(new Map(classes.filter(item => item.teacher_id != null).map(item => [item.teacher_id!,
    item.teacher_name || teachers.find(teacher => teacher.id === item.teacher_id)?.name || '已绑定（姓名不可用）'])),
    ([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
  const addedHours = editing.reduce((total, item) => total + (item.teacher_id === teacherId ? 0 : item.weekly_periods), 0)
  return <section>
    <p>{academicYear} · 第 {term} 学期 · 教学班任教关系</p>
    <Alert type="info" showIcon message="按教师关联的学科组安排教学班。周课时合计包含本学期所有年级的行政任教课时和走班课时；已有走班课表的班级不能直接换教师。" />
    {error && <Alert type="error" showIcon message={error} />}
    <Space wrap style={{ margin: '16px 0' }}>
      <Select aria-label="教学班任教年级" style={{ width: 180 }} value={gradeId} disabled={saving} onChange={setGradeId} options={grades.map((item) => ({ value: item.id, label: item.name }))} />
      <Select aria-label="教学班任教学科" style={{ width: 150 }} value={subjectId} allowClear disabled={loading || saving} placeholder="全部科目" onChange={(value) => { setSubjectId(value); setSelectedIds([]); setPage(1) }}
        options={Array.from(new Map(classes.map((item) => [item.subject_id, item.subject_name])), ([value, label]) => ({ value, label }))} />
      <Select aria-label="教学班教师筛选" style={{ width: 180 }} value={filterTeacherId} allowClear showSearch optionFilterProp="label"
        disabled={loading || saving} placeholder="全部教师" options={filterTeacherOptions} notFoundContent="没有匹配的教师"
        onChange={(value) => { setFilterTeacherId(value); setSelectedIds([]); setPage(1) }} />
      <Button disabled={!selectedIds.length || loading || saving} onClick={() => edit(classes.filter((item) => selectedIds.includes(item.id)))}>批量安排教师</Button>
      <Button loading={loading} disabled={saving} onClick={() => setRevision((value) => value + 1)}>刷新</Button>
      {!loading && !error && <span>{subjectId !== undefined || filterTeacherId !== undefined ? '筛选结果' : '共'} {visibleClasses.length} 个班 · 已安排 {visibleClasses.filter((item) => item.teacher_id).length} 个 · 未安排 {visibleClasses.filter((item) => !item.teacher_id).length} 个</span>}
    </Space>
    <Table<WalkTeachingClass> rowKey="id" loading={loading} dataSource={visibleClasses} scroll={{ x: 850 }}
      rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds, getCheckboxProps: () => ({ disabled: saving }) }}
      pagination={{ current: page, onChange: setPage, pageSize: 10, showSizeChanger: false }} locale={{ emptyText: error ? '加载失败，请刷新' : classes.length ? '没有符合筛选条件的教学班，请调整科目或教师筛选' : '本年级本学期尚未生成教学班' }} columns={[
        { title: '科目', dataIndex: 'subject_name' }, { title: '教学班', dataIndex: 'name' },
        { title: '人数', dataIndex: 'student_count' }, { title: '每周课时', dataIndex: 'weekly_periods' },
        { title: '任课教师', render: (_, item) => item.teacher_name || (item.teacher_id ? '已绑定（姓名不可用）' : '未安排') },
        { title: '状态', render: (_, item) => <Tag color={item.teacher_id ? 'green' : 'orange'}>{item.teacher_id ? '已安排' : '未安排'}</Tag> },
        { title: '操作', render: (_, item) => <Space><Button type="link" disabled={saving} onClick={() => edit([item])}>{item.teacher_id ? '更换教师' : '安排教师'}</Button>
          {Boolean(item.teacher_id) && <Button type="link" danger disabled={saving} onClick={() => edit([item], true)}>解除</Button>}</Space> },
      ]} />
    <Modal title={removing ? '解除教学班任教关系' : '安排教学班教师'} open={editing.length > 0} onCancel={() => { if (!saving) setEditing([]) }}
      confirmLoading={saving} okText="确认保存" cancelText="取消" onOk={() => void save()} okButtonProps={{ disabled: !removing && !teacherId }}>
      <p>{editing.map((item) => item.name).join('、')}</p>
      {removing ? <Alert type="warning" showIcon message="解除后该班将显示未安排教师。已有走班课表时操作会被拒绝。" /> : <>
        <Select aria-label="教学班任课教师" showSearch optionFilterProp="label" style={{ width: '100%' }} value={teacherId} disabled={saving} onChange={setTeacherId}
          placeholder="选择关联该学科组的教师" options={teachers.filter((item) => item.subject_ids.includes(editing[0]?.subject_id)).map((item) => ({ value: item.id,
            label: `${item.name} · 行政 ${item.administrative_periods} + 走班 ${item.walk_periods} = ${item.total_periods} 节/周` }))} />
        {teacher && <p>保存后该教师合计 {teacher.total_periods + addedHours} 节/周（本次增加 {addedHours} 节）。</p>}
        <p>没有可选教师时，请先在组织关系中将教师加入对应学科组。</p>
      </>}
    </Modal>
  </section>
}
