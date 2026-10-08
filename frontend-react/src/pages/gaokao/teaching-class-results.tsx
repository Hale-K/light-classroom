import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Modal, Select, Space, Table, Tag } from 'antd'
import { gaokaoApi } from '@/api'
import { useNavigate } from 'react-router-dom'
import type { WalkTeachingClass } from '@/api'

export default function TeachingClassResults({ gradeId, academicYear, term, gradeName, onClose }: {
  gradeId: number; academicYear: string; term: string; gradeName?: string; onClose: () => void
}) {
  const navigate = useNavigate()
  const [classes, setClasses] = useState<WalkTeachingClass[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [subjectId, setSubjectId] = useState<number>()
  const [selectedClass, setSelectedClass] = useState<WalkTeachingClass>()
  const [search, setSearch] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setSelectedClass(undefined)
    gaokaoApi.teachingClasses({ grade_id: gradeId, academic_year: academicYear, term })
      .then((data) => { if (active) setClasses(data) })
      .catch((e) => { if (active) { setClasses([]); setError(e instanceof Error ? e.message : '教学班结果加载失败') } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [gradeId, academicYear, term, revision])

  const subjects = useMemo(() => Array.from(new Map(classes.map((item) => [item.subject_id, item.subject_name])).entries()), [classes])
  const visibleClasses = classes.filter((item) => subjectId === undefined || item.subject_id === subjectId)
  const studentCount = new Set(classes.flatMap((item) => item.students.map((student) => student.id))).size
  const members = (selectedClass?.students ?? []).filter((student) =>
    `${student.name} ${student.student_no ?? ''} ${student.administrative_class ?? ''}`.includes(search.trim()))

  return <>
    <Modal title="已生成教学班结果" open width={1100} onCancel={onClose} footer={<Button onClick={onClose}>关闭</Button>}>
      <p>{gradeName} · {academicYear} · 第 {term} 学期</p>
      <Alert type="info" showIcon message={classes.length > 0 && studentCount === 0
        ? '教学班已生成，当前尚未分配学生；学生分班和课表将在联合排课确认时一起保存。'
        : '这里展示已保存的教学班和学生名单。生成班级后，还需要安排教师、教室及课表。'} />
      {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message={error} action={<Button onClick={() => setRevision((value) => value + 1)}>重试</Button>} />}
      <Space wrap style={{ margin: '16px 0' }}>
        <Button type="primary" onClick={() => navigate(`/scheduling?tab=assignments&assignmentMode=walk&grade=${gradeId}`)}>安排教师</Button>
        <Select aria-label="教学班科目筛选" allowClear placeholder="全部科目" style={{ width: 160 }} value={subjectId} onChange={setSubjectId}
          options={subjects.map(([value, label]) => ({ value, label }))} />
        <Button loading={loading} onClick={() => setRevision((value) => value + 1)}>刷新结果</Button>
        {!loading && !error && <span>共 {classes.length} 个教学班 · {studentCount} 名学生 · {classes.reduce((total, item) => total + item.student_count, 0)} 人次选课</span>}
      </Space>
      <Table<WalkTeachingClass> rowKey="id" loading={loading} dataSource={visibleClasses} scroll={{ x: 850 }} size="small"
        pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 个班` }}
        locale={{ emptyText: error ? '加载失败，请重试' : '本年级本学期尚未生成教学班' }} columns={[
          { title: '教学班', dataIndex: 'name' },
          { title: '科目', dataIndex: 'subject_name' },
          { title: '人数 / 上限', render: (_, item) => `${item.student_count} / ${item.capacity}` },
          { title: '每周课时', render: (_, item) => <>{item.weekly_periods} {item.hours_overridden && <Tag>单班调整</Tag>}</> },
          { title: '教师', render: (_, item) => item.teacher_name ?? (item.teacher_id ? '已绑定（姓名不可用）' : '未安排') },
          { title: '教室', render: (_, item) => item.room || '未安排' },
          { title: '操作', render: (_, item) => <Button type="link" disabled={!item.student_count} onClick={() => { setSelectedClass(item); setSearch('') }}>
            {item.student_count ? '查看名单' : '尚未分班'}
          </Button> },
        ]} />
    </Modal>
    <Modal title={`${selectedClass?.name ?? ''} · 学生名单`} open={Boolean(selectedClass)} width={780} onCancel={() => setSelectedClass(undefined)}
      footer={<Button onClick={() => setSelectedClass(undefined)}>关闭名单</Button>}>
      <p>{selectedClass?.subject_name} · 共 {selectedClass?.student_count ?? 0} 人</p>
      <Input aria-label="教学班学生搜索" placeholder="搜索姓名、学号或行政班" allowClear value={search} onChange={(event) => setSearch(event.target.value)} style={{ marginBottom: 12 }} />
      <Table rowKey="id" dataSource={members} size="small" pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 人` }} columns={[
        { title: '学号', dataIndex: 'student_no', render: (value) => value || '—' },
        { title: '姓名', dataIndex: 'name' },
        { title: '所属行政班', dataIndex: 'administrative_class', render: (value) => value || '未分行政班' },
      ]} />
    </Modal>
  </>
}
