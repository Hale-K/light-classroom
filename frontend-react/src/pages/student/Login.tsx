import { useEffect, useState } from 'react'
import { App, Button, Card, Form, Input, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { studentAuthApi } from '@/api'

export default function StudentLogin() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (localStorage.getItem('zh_student_token')) navigate('/student/choice', { replace: true })
  }, [navigate])

  const submit = async (values: { school_code: string; login_name: string; password: string }) => {
    setSubmitting(true)
    try {
      localStorage.setItem('zh_school_code', values.school_code.trim())
      const result = await studentAuthApi.login({ login_name: values.login_name, password: values.password })
      localStorage.setItem('zh_student_token', result.access_token)
      localStorage.setItem('zh_student_user', JSON.stringify(result.student))
      message.success(`欢迎你，${result.student.name}`)
      navigate('/student/choice', { replace: true })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败，请检查账号信息')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'linear-gradient(135deg, #eff8ff, #f8fafc)', padding: 24 }}>
      <Card style={{ width: 'min(440px, 100%)', borderRadius: 20 }}>
        <Typography.Text type="secondary">LIGHTCLASS · STUDENT PORTAL</Typography.Text>
        <Typography.Title level={2} style={{ marginTop: 8 }}>学生选科中心</Typography.Title>
        <Typography.Paragraph type="secondary">登录后提交或修改本学期的 3+1+2 选科意向。</Typography.Paragraph>
        <Form layout="vertical" onFinish={submit} initialValues={{ school_code: localStorage.getItem('zh_school_code') || 'demo' }}>
          <Form.Item name="school_code" label="学校代码" rules={[{ required: true, message: '请输入学校代码' }]}>
            <Input placeholder="例如 demo" />
          </Form.Item>
          <Form.Item name="login_name" label="学生账号" rules={[{ required: true, message: '请输入学生账号' }]}>
            <Input placeholder="使用学校开通的学生账号" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password placeholder="请输入密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>登录选科中心</Button>
        </Form>
      </Card>
    </main>
  )
}
