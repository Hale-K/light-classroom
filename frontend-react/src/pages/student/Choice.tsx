import { useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Empty, Form, Select, Space, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { studentAuthApi } from '@/api'
import type { StudentChoiceOptions } from '@/api'

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
      if (result.choice) {
        form.setFieldsValue({
          primary_subject_id: result.choice.primary_subject_id,
          secondary_subject_ids: result.choice.secondary_subject_ids,
        })
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '选科信息加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!localStorage.getItem('zh_student_token')) {
      navigate('/student/login', { replace: true })
      return
    }
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const subjectMap = useMemo(() => new Map((data?.subjects || []).map((item) => [item.id, item.name])), [data])
  const submit = async (status: 'draft' | 'confirmed') => {
    const values = await form.validateFields()
    if (!data?.scheme) return
    if (!academicYear || !term) return
    setSaving(true)
    try {
      await studentAuthApi.saveChoice({
        scheme_id: data.scheme.id,
        academic_year: academicYear,
        effective_term: term,
        primary_subject_id: values.primary_subject_id,
        secondary_subject_ids: values.secondary_subject_ids,
        status,
      })
      message.success(status === 'confirmed' ? '选科已提交，请等待教务确认' : '选科草稿已保存')
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

  if (!loading && !data?.scheme) return <Empty description="学校尚未配置高考方案" style={{ marginTop: 120 }} />
  const scheme = data?.scheme
  const choice = data?.choice
  return (
    <main style={{ minHeight: '100vh', background: '#f5f8fb', padding: '36px 20px' }}>
      <div style={{ maxWidth: 760, margin: '0 auto' }}>
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <Card loading={loading} style={{ borderRadius: 18 }}>
            <Space direction="vertical" size={4}>
              <Typography.Text type="secondary">STUDENT CHOICE CENTER · {academicYear || '当前学年'}</Typography.Text>
              <Typography.Title level={2} style={{ margin: 0 }}>我的高考选科</Typography.Title>
              <Typography.Text type="secondary">当前方案：{scheme?.name} · {scheme?.mode}</Typography.Text>
              {choice && (
                <Tag color={choice.status === 'confirmed' ? 'green' : choice.status === 'locked' ? 'blue' : choice.status === 'rejected' ? 'red' : 'gold'}>
                  {choice.status === 'confirmed' ? '待班主任审核' : choice.status === 'locked' ? '审核通过' : choice.status === 'rejected' ? '已驳回，可重新提交' : '草稿'}
                </Tag>
              )}
            </Space>
            <Button type="link" onClick={logout} style={{ float: 'right', marginTop: -36 }}>退出登录</Button>
          </Card>
          <Card title="提交你的选科组合" style={{ borderRadius: 18 }}>
            <Typography.Paragraph type="secondary">3+1+2：首选科目 1 门，再选科目 2 门。提交后由教务审核，锁定后不能自行修改。</Typography.Paragraph>
            <Form form={form} layout="vertical">
              <Form.Item name="primary_subject_id" label="首选科目（物理 / 历史二选一）" rules={[{ required: true, message: '请选择首选科目' }]}>
                <Select options={(scheme?.primary_subject_ids || []).map((id) => ({ value: id, label: subjectMap.get(id) || `科目 ${id}` }))} />
              </Form.Item>
              <Form.Item name="secondary_subject_ids" label="再选科目（四选二）" rules={[{ required: true, message: '请选择两门再选科目' }]}>
                <Select mode="multiple" maxCount={2} options={(scheme?.secondary_subject_ids || []).map((id) => ({ value: id, label: subjectMap.get(id) || `科目 ${id}` }))} />
              </Form.Item>
              <Space>
                <Button onClick={() => void submit('draft')} loading={saving}>保存草稿</Button>
                <Button type="primary" onClick={() => void submit('confirmed')} loading={saving}>提交选科</Button>
              </Space>
            </Form>
          </Card>
        </Space>
      </div>
    </main>
  )
}
