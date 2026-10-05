import { App, Button, Empty, Popconfirm, Select, Space, Spin, Table, Tag } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useEffect, useMemo, useState } from 'react'
import { authApi, gaokaoApi } from '@/api'
import type { GaokaoChoiceReview } from '@/api'
import type { Student } from '@/types'
import TableCard from '@/components/TableCard'
import { useAuthStore } from '@/store/auth'
import './TeacherStudents.css'

type StudentReviewRow = Student & { choice?: GaokaoChoiceReview }

/**
 * 教师端 · 选科审核
 * 班主任在这里审核本班学生的 3+1+2 选科意愿；数据范围由后端按班主任任职关系强制限定。
 */
export default function TeacherStudents() {
  const { message } = App.useApp()
  const user = useAuthStore((state) => state.user)
  const canReview = (user?.roles || []).includes('head_teacher')
  const [academicYear, setAcademicYear] = useState('2026-2027')
  const [term, setTerm] = useState('1')
  const [students, setStudents] = useState<StudentReviewRow[]>([])
  const [loading, setLoading] = useState(false)
  const [actionId, setActionId] = useState<number>()
  const [selectedStudentIds, setSelectedStudentIds] = useState<number[]>([])
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'locked' | 'rejected' | 'unsubmitted'>('all')
  const [classFilter, setClassFilter] = useState('all')

  const loadChoices = async () => {
    if (!canReview) return
    setLoading(true)
    try {
      const settings = await authApi.academicYears().catch(() => null)
      const year = settings?.current_academic_year || academicYear
      const currentTerm = settings?.current_term || term
      setAcademicYear(year)
      setTerm(currentTerm)
      const [studentResult, choiceResult, legacyChoiceResult] = await Promise.all([
        gaokaoApi.myStudents(),
        gaokaoApi.choicesForReview({ academic_year: year, term: currentTerm, status_filter: '' }),
        currentTerm === '1'
          ? Promise.resolve([] as GaokaoChoiceReview[])
          : gaokaoApi.choicesForReview({ academic_year: year, term: '1', status_filter: '' }).catch(() => []),
      ])
      const choicesByStudent = new Map([...legacyChoiceResult, ...choiceResult].map((choice) => [choice.student_id, choice]))
      setStudents(studentResult.map((student) => ({ ...student, choice: choicesByStudent.get(student.id) })))
      setSelectedStudentIds([])
    } catch (error) {
      message.error(error instanceof Error ? error.message : '学生选科加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadChoices()
    // 只在身份状态确定后首次加载；操作完成时由调用方主动刷新。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canReview])

  const review = async (choiceId: number, action: 'approve' | 'reject' | 'reopen') => {
    setActionId(choiceId)
    try {
      await gaokaoApi.reviewChoice(choiceId, action)
      setStudents((items) => items.map((item) => item.choice?.id === choiceId
        ? { ...item, choice: { ...item.choice, status: action === 'approve' ? 'locked' : action === 'reopen' ? 'confirmed' : 'rejected' } }
        : item))
      setSelectedStudentIds((ids) => ids.filter((id) => !students.some((student) => student.id === id && student.choice?.id === choiceId)))
      message.success(action === 'approve' ? '已通过并锁定该学生选科' : action === 'reopen' ? '已解除锁定，退回待审核' : '已驳回，该学生可重新提交')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '审核失败')
    } finally {
      setActionId(undefined)
    }
  }

  const batchApprove = async () => {
    const choiceIds = students.filter((student) => selectedStudentIds.includes(student.id) && student.choice).map((student) => student.choice!.id)
    if (!choiceIds.length) return
    setLoading(true)
    try {
      const result = await gaokaoApi.batchApproveChoices(choiceIds)
      setStudents((items) => items.map((item) => item.choice && choiceIds.includes(item.choice.id)
        ? { ...item, choice: { ...item.choice, status: 'locked' } }
        : item))
      setSelectedStudentIds([])
      message.success(`已通过 ${result.updated} 人${result.skipped ? `，跳过 ${result.skipped} 人` : ''}`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量审核失败')
    } finally {
      setLoading(false)
    }
  }

  const classOptions = useMemo(() => {
    const classes = new Map<number, string>()
    students.forEach((student) => {
      if (student.class_id != null) classes.set(student.class_id, student.class_name || '未命名班级')
    })
    return [
      { value: 'all', label: '全部班级' },
      ...Array.from(classes.entries()).sort((a, b) => a[1].localeCompare(b[1], 'zh-CN')).map(([id, name]) => ({ value: String(id), label: name })),
    ]
  }, [students])

  const visibleStudents = useMemo(() => students.filter((student) => {
    if (classFilter !== 'all' && String(student.class_id) !== classFilter) return false
    if (statusFilter === 'all') return true
    if (statusFilter === 'unsubmitted') return !student.choice
    return student.choice?.status === (statusFilter === 'pending' ? 'confirmed' : statusFilter)
  }), [classFilter, statusFilter, students])

  const columns = useMemo(() => [
    {
      title: '学生',
      key: 'student',
      render: (_: unknown, item: StudentReviewRow) => (
        <div className="ts-student-cell"><strong>{item.name}</strong><span>{item.student_no || '—'}{item.class_name ? ` · ${item.class_name}` : ''}</span></div>
      ),
    },
    { title: '首选科目', key: 'primary', render: (_: unknown, item: StudentReviewRow) => item.choice?.primary_subject_name || <span className="ts-muted">未提交</span> },
    {
      title: '再选科目',
      key: 'secondary',
      render: (_: unknown, item: StudentReviewRow) => item.choice?.secondary_subject_names.join('、') || <span className="ts-muted">—</span>,
    },
    { title: '轮次', key: 'round', render: (_: unknown, item: StudentReviewRow) => item.choice ? <Tag>第 {item.choice.round_no} 轮</Tag> : <span className="ts-muted">未提交</span> },
    {
      title: '状态',
      key: 'status',
      render: (_: unknown, item: StudentReviewRow) => item.choice?.status === 'locked' ? (
        <Tag color="success" icon={<CheckCircleOutlined />}>已通过并锁定</Tag>
      ) : item.choice?.status === 'rejected' ? (
        <Tag color="error">已驳回</Tag>
      ) : item.choice?.status === 'confirmed' ? (
        <Tag color="warning">待审核</Tag>
      ) : item.choice?.status === 'draft' ? (
        <Tag>草稿</Tag>
      ) : <span className="ts-muted">未提交</span>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, item: StudentReviewRow) => item.choice?.status === 'locked' ? (
        <Popconfirm title="解除锁定并退回待审核？" onConfirm={() => void review(item.choice!.id, 'reopen')} okText="确认修改" cancelText="取消">
          <Button size="small" type="link">修改审核</Button>
        </Popconfirm>
      ) : item.choice?.status === 'confirmed' ? (
        <Space>
          <Button type="primary" size="small" loading={actionId === item.choice.id} onClick={() => void review(item.choice!.id, 'approve')}>通过并锁定</Button>
          <Popconfirm title="确认驳回该学生的选科意愿？" onConfirm={() => void review(item.choice!.id, 'reject')} okText="驳回" cancelText="取消">
            <Button size="small" danger disabled={actionId !== undefined}>驳回</Button>
          </Popconfirm>
        </Space>
      ) : <span className="ts-muted">—</span>,
    },
  ], [actionId, students])

  return (
    <div className="ts-page">
      <section className="ts-body">
        {!canReview ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前账号不是班主任，暂无本班学生审核权限。" />
        ) : (
          <TableCard
            title={<span className="ts-card-title">本班选科审核 <Tag color="blue">共 {students.length} 人</Tag> <Tag color="orange">待审核 {students.filter((item) => item.choice?.status === 'confirmed').length} 人</Tag></span>}
            extra={(
              <Space>
                <Select value={classFilter} style={{ width: 140 }} onChange={setClassFilter} options={classOptions} />
                <Select
                  value={statusFilter}
                  style={{ width: 130 }}
                  onChange={setStatusFilter}
                  options={[
                    { value: 'all', label: '全部状态' },
                    { value: 'pending', label: '待审核' },
                    { value: 'locked', label: '已通过' },
                    { value: 'rejected', label: '已驳回' },
                    { value: 'unsubmitted', label: '未提交' },
                  ]}
                />
                <Button onClick={() => void loadChoices()}>刷新</Button>
                <Popconfirm title={`确认通过选中的 ${selectedStudentIds.length} 人？`} onConfirm={() => void batchApprove()} okText="通过并锁定" cancelText="取消" disabled={!selectedStudentIds.length}>
                  <Button type="primary" disabled={!selectedStudentIds.length} loading={loading}>批量通过并锁定</Button>
                </Popconfirm>
              </Space>
            )}
          >
            <div className="ts-review-head"><span>{academicYear} · 第 {term} 学期</span></div>
            <Spin spinning={loading}>
              <Table
                rowKey="id"
                columns={columns}
                dataSource={visibleStudents}
                pagination={{
                  defaultPageSize: 10,
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50],
                  showTotal: (total) => `共 ${total} 名学生`,
                }}
                rowSelection={{
                  selectedRowKeys: selectedStudentIds,
                  preserveSelectedRowKeys: true,
                  onChange: (keys) => setSelectedStudentIds(keys as number[]),
                  getCheckboxProps: (item) => ({ disabled: item.choice?.status !== 'confirmed' }),
                }}
                locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前班级暂无学生" /> }}
              />
            </Spin>
          </TableCard>
        )}
      </section>
    </div>
  )
}
