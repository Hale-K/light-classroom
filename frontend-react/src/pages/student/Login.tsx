import { translate as t, useLocale } from '@/i18n'
import { useEffect, useState } from 'react'
import { App, Button, Form, Input, Select, Spin, Typography } from 'antd'
import { ApartmentOutlined, ArrowRightOutlined, LockOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { studentAuthApi } from '@/api'
import type { StudentSchoolOption } from '@/api'
import './student.css'

type LoginValues = { school_code: string; login_name: string; password: string }

export default function StudentLogin() {
  useLocale()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [schools, setSchools] = useState<StudentSchoolOption[]>([])
  const [loadingSchools, setLoadingSchools] = useState(true)

  useEffect(() => {
    if (localStorage.getItem('zh_student_token')) {
      navigate('/student/choice', { replace: true })
      return
    }
    studentAuthApi.schools()
      .then(setSchools)
      .catch((error) => message.error(error instanceof Error ? error.message : t("学校列表加载失败")))
      .finally(() => setLoadingSchools(false))
  }, [message, navigate])

  const submit = async (values: LoginValues) => {
    setSubmitting(true)
    try {
      localStorage.setItem('zh_school_code', values.school_code)
      const result = await studentAuthApi.login({ login_name: values.login_name, password: values.password })
      localStorage.setItem('zh_student_token', result.access_token)
      localStorage.setItem('zh_student_user', JSON.stringify(result.student))
      message.success(t("欢迎你，{{p0}}", { p0: result.student.name }))
      navigate('/student/choice', { replace: true })
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("登录失败，请检查账号信息"))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="student-shell student-login-shell">
      <section className="student-login-card" aria-labelledby="student-login-title">
        <div className="student-brand-mark" aria-hidden="true"><ApartmentOutlined /></div>
        <Typography.Text className="student-eyebrow">{t("轻课堂 · 学生端")}</Typography.Text>
        <Typography.Title id="student-login-title" level={1}>{t("登录选科中心")}</Typography.Title>
        <Typography.Paragraph className="student-login-lede">{t("选择学校后，使用学校开通的学号登录。")}</Typography.Paragraph>

        <Form layout="vertical" onFinish={submit} initialValues={{ school_code: localStorage.getItem('zh_school_code') || undefined }}>
          <Form.Item name="school_code" label={t("学校")} rules={[{ required: true, message: t("请选择学校") }]}>
            <Select
              size="large"
              showSearch
              loading={loadingSchools}
              placeholder={loadingSchools ? t("正在加载学校") : t("请选择学校")}
              optionFilterProp="label"
              options={schools.map((school) => ({ value: school.code, label: school.name }))}
              notFoundContent={loadingSchools ? <Spin size="small" /> : t("暂无可选学校")}
            />
          </Form.Item>
          <Form.Item name="login_name" label={t("学生账号")} rules={[{ required: true, message: t("请输入学生账号") }]}>
            <Input size="large" prefix={<UserOutlined />} placeholder={t("请输入学号")} autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label={t("密码")} rules={[{ required: true, message: t("请输入密码") }]}>
            <Input.Password size="large" prefix={<LockOutlined />} placeholder={t("请输入密码")} autoComplete="current-password" />
          </Form.Item>
          <Button className="student-primary-button" type="primary" htmlType="submit" block loading={submitting} icon={<ArrowRightOutlined />}>
            {t("进入选科中心")}</Button>
        </Form>
        <div className="student-ends">
          {t("其他端：")}<a onClick={() => navigate('/login')}>{t("教师工作台")}</a>
          ·
          <a onClick={() => navigate('/admin/login')}>{t("平台超管")}</a>
        </div>
      </section>
    </main>
  )
}
