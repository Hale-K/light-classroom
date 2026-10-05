import { useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Empty, Form, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, LogoutOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { studentAuthApi } from '@/api'
import type { StudentChoiceOptions } from '@/api'
import './student.css'

export default function StudentChoice() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [data, setData] = useState<StudentChoiceOptions>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [academicYear, setAcademicYear] = useState<string>()
  const [term, setTerm] = useState<string>()

  const load = async () => {
    setLoading(true)
    try {
      const context = await studentAuthApi.context()
      setAcademicYear(context.academic_year)
      setTerm(context.term)
      const result = await studentAuthApi.options({ academic_year: context.academic_year, term: context.term })
      setData(result)
      if (result.choice) form.setFieldsValue({ primary_subject_id: result.choice.primary_subject_id, secondary_subject_ids: result.choice.secondary_subject_ids })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '选科信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!localStorage.getItem('zh_student_token')) { navigate('/student/login', { replace: true }); return }
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const subjectMap = useMemo(() => new Map((data?.subjects || []).map((item) => [item.id, item.name])), [data])
  const choice = data?.choice
  const locked = choice?.status === 'locked'
  const statusConfig = choice?.status === 'locked'
    ? { text: '已通过，选科已锁定', color: 'success', icon: <CheckCircleOutlined /> }
    : choice?.status === 'confirmed'
      ? { text: '已提交，等待班主任审核', color: 'processing', icon: <ClockCircleOutlined /> }
      : choice?.status === 'rejected'
        ? { text: '已退回，请修改后重新提交', color: 'error', icon: <ClockCircleOutlined /> }
        : choice?.status === 'draft'
          ? { text: '草稿', color: 'warning', icon: <SaveOutlined /> }
          : null

  const submit = async (nextStatus: 'draft' | 'confirmed') => {
    const values = await form.validateFields()
    if (!data?.scheme || !academicYear || !term || locked) return
    setSaving(true)
    try {
      await studentAuthApi.saveChoice({ scheme_id: data.scheme.id, academic_year: academicYear, effective_term: term, primary_subject_id: values.primary_subject_id, secondary_subject_ids: values.secondary_subject_ids, status: nextStatus })
      message.success(nextStatus === 'confirmed' ? '已提交，等待班主任审核' : '草稿已保存')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '选科保存失败')
    } finally {
      setSaving(false)
    }
  }

  const logout = () => {
    localStorage.removeItem('zh_student_token')
    localStorage.removeItem('zh_student_user')
    navigate('/student/login', { replace: true })
  }

  if (loading) return <main className="student-shell"><div className="student-page"><Skeleton active paragraph={{ rows: 7 }} /></div></main>
  if (!data?.scheme) return <main className="student-shell"><div className="student-page student-empty"><Empty description="学校尚未配置选科方案" /></div></main>

  const scheme = data.scheme
  const primaryOptions = scheme.primary_subject_ids.map((id) => ({ value: id, label: subjectMap.get(id) || `科目 ${id}` }))
  const secondaryOptions = scheme.secondary_subject_ids.map((id) => ({ value: id, label: subjectMap.get(id) || `科目 ${id}` }))

  return (
    <main className="student-shell">
      <div className="student-page">
        <header className="student-page-header">
          <div>
            <Typography.Text className="student-eyebrow">学生选科</Typography.Text>
            <Typography.Title level={1}>我的选科</Typography.Title>
            <Typography.Text type="secondary">{academicYear} · 第 {term} 学期</Typography.Text>
          </div>
          <Button type="text" icon={<LogoutOutlined />} onClick={logout}>退出</Button>
        </header>

        <Card className="student-status-card" bordered={false}>
          <div>
            <Typography.Text type="secondary">当前方案</Typography.Text>
            <Typography.Title level={3}>{scheme.name}</Typography.Title>
            <Typography.Text type="secondary">3+1+2</Typography.Text>
          </div>
          {statusConfig && <Tag color={statusConfig.color} icon={statusConfig.icon}>{statusConfig.text}</Tag>}
        </Card>

        <Card className="student-choice-card" bordered={false} title="选择科目">
          <div className="student-choice-rule">首选 1 门 · 再选 2 门</div>
          <Form form={form} layout="vertical" disabled={locked}>
            <Form.Item name="primary_subject_id" label="首选科目" rules={[{ required: true, message: '请选择首选科目' }]}>
              <Select size="large" placeholder="请选择物理或历史" options={primaryOptions} />
            </Form.Item>
            <Form.Item name="secondary_subject_ids" label="再选科目" rules={[{ required: true, message: '请选择两门再选科目' }]}>
              <Select size="large" mode="multiple" maxCount={2} placeholder="请选择两门科目" options={secondaryOptions} />
            </Form.Item>
            <div className="student-actions">
              {locked ? <Typography.Text type="secondary">审核通过后不能修改</Typography.Text> : <Space>
                <Button icon={<SaveOutlined />} onClick={() => void submit('draft')} loading={saving}>保存草稿</Button>
                <Button type="primary" icon={<SendOutlined />} onClick={() => void submit('confirmed')} loading={saving}>提交选科</Button>
              </Space>}
            </div>
          </Form>
        </Card>
      </div>
    </main>
  )
}
