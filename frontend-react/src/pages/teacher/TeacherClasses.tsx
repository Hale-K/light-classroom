import { App, Empty, Input, Select, Space, Spin, Table, Tag } from 'antd'
import { SearchOutlined, TeamOutlined } from '@ant-design/icons'
import { useEffect, useMemo, useState } from 'react'
import { gaokaoApi } from '@/api'
import type { Student } from '@/types'
import TableCard from '@/components/TableCard'
import './TeacherClasses.css'

function studentStatusLabel(status?: string) {
  switch (status) {
    case 'studying':
    case '在读':
      return '在读'
    case 'graduated':
    case '毕业':
      return '已毕业'
    case 'suspended':
    case '休学':
      return '休学'
    case 'transferred':
    case '转学':
      return '已转学'
    default:
      return status || '在读'
  }
}

function genderLabel(gender?: string) {
  if (gender === 'male' || gender === '男') return '男'
  if (gender === 'female' || gender === '女') return '女'
  return gender || '—'
}

/**
 * 教师端 · 学生管理
 * 只展示当前教师负责班级的学生；选科审核由“选课审核”菜单单独负责。
 */
export default function TeacherClasses() {
  const { message } = App.useApp()
  const [students, setStudents] = useState<Student[]>([])
  const [loading, setLoading] = useState(true)
  const [classFilter, setClassFilter] = useState('all')
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    let active = true
    gaokaoApi.myStudents(true)
      .then((result) => {
        if (active) setStudents(result)
      })
      .catch((error) => {
        if (active) message.error(error instanceof Error ? error.message : '学生信息加载失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [message])

  const classOptions = useMemo(() => {
    const classes = new Map<number, string>()
    students.forEach((student) => {
      if (student.class_id != null) classes.set(student.class_id, student.class_name || '未命名班级')
    })
    return [
      { value: 'all', label: '全部班级' },
      ...Array.from(classes.entries())
        .sort((a, b) => a[1].localeCompare(b[1], 'zh-CN'))
        .map(([id, name]) => ({ value: String(id), label: name })),
    ]
  }, [students])

  const visibleStudents = useMemo(() => {
    const normalized = keyword.trim().toLowerCase()
    return students.filter((student) => {
      const sameClass = classFilter === 'all' || String(student.class_id) === classFilter
      const matchesKeyword = !normalized || [student.name, student.student_no, student.class_name]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized))
      return sameClass && matchesKeyword
    })
  }, [classFilter, keyword, students])

  const columns = useMemo(() => [
    {
      title: '学生',
      key: 'student',
      render: (_: unknown, student: Student) => (
        <div className="tm-student-cell">
          <strong>{student.name}</strong>
          <span>{student.student_no || '暂无学号'}</span>
        </div>
      ),
    },
    { title: '班级', dataIndex: 'class_name', key: 'class_name', render: (value: string | null) => value || '未分班' },
    { title: '性别', dataIndex: 'gender', key: 'gender', render: (value: string | undefined) => genderLabel(value) },
    {
      title: '学籍状态',
      dataIndex: 'status',
      key: 'status',
      render: (value: string | undefined) => <Tag color={studentStatusLabel(value) === '在读' ? 'success' : 'default'}>{studentStatusLabel(value)}</Tag>,
    },
  ], [])

  return (
    <div className="tm-page">
      <div className="tm-title-row">
        <div>
          <div className="tm-eyebrow">学生管理</div>
          <h1>我的学生</h1>
          <p>管理本人班主任班级及任课班级的学生信息。</p>
        </div>
        <div className="tm-total"><TeamOutlined /> 共 {students.length} 人</div>
      </div>

      <TableCard
        title={<span className="tm-card-title">本班学生 <Tag color="blue">{visibleStudents.length} 人</Tag></span>}
        extra={<Space wrap>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索姓名或学号"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            style={{ width: 200 }}
          />
          <Select value={classFilter} options={classOptions} onChange={setClassFilter} style={{ width: 140 }} />
        </Space>}
      >
        {loading ? <div className="tm-loading"><Spin /></div> : visibleStudents.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={students.length ? '没有匹配的学生' : '暂无负责班级的学生'} />
        ) : (
          <Table<Student>
            rowKey="id"
            columns={columns}
            dataSource={visibleStudents}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 人` }}
            scroll={{ x: 680 }}
          />
        )}
      </TableCard>
    </div>
  )
}
