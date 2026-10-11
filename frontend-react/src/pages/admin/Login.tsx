import { translate as t, useLocale } from '@/i18n'
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { App, Button, Form, Input } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminStore } from '@/store/admin'
import { APP_NAME, APP_NAME_EN } from '@/types'

interface AdminLoginForm {
  username: string
  password: string
}

const styles: Record<string, CSSProperties> = {
  card: { padding: '32px 28px 24px' },
  brand: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 },
  brandName: { fontSize: 17, fontWeight: 700, color: 'var(--ink)' },
  brandSub: { marginTop: 2, fontSize: 12, color: 'var(--text-3)' },
  submit: { marginTop: 4, height: 44 },
  hint: { marginTop: 18, textAlign: 'center', fontSize: 12, color: 'var(--text-3)' },
}

export default function AdminLogin() {
  useLocale()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const login = useAdminStore((s) => s.login)
  const [loading, setLoading] = useState(false)

  // 已登录访问登录页 → 直接进入学校管理（仅挂载时判断一次）
  useEffect(() => {
    if (useAdminStore.getState().token) navigate('/admin/schools', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const from = (location.state as { from?: string } | null)?.from

  const onFinish = async (values: AdminLoginForm) => {
    if (!values.username || !values.password) {
      message.warning(t("请输入账号和密码"))
      return
    }
    setLoading(true)
    try {
      await login(values.username, values.password)
      navigate(from || '/admin/schools', { replace: true })
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("登录失败，请重试"))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-bg">
      <div className="login-card" style={styles.card}>
        <div style={styles.brand}>
          <div className="brand-mark brand-mark-admin">{t("管")}</div>
          <div>
            <div style={styles.brandName}>{t("平台管理后台")}</div>
            <div style={styles.brandSub}>
              {APP_NAME} {APP_NAME_EN} {t("· 学校开通与运营")}</div>
          </div>
        </div>

        <Form<AdminLoginForm> layout="vertical" requiredMark={false} onFinish={onFinish}>
          <Form.Item name="username" rules={[{ required: true, message: t("请输入管理员账号") }]}>
            <Input size="large" placeholder={t("管理员账号")} autoFocus />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: t("请输入登录密码") }]}>
            <Input.Password size="large" placeholder={t("登录密码")} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" style={styles.submit} loading={loading}>
            {t("登 录")}</Button>
        </Form>

        <div style={styles.hint}>
          {t("其他端：")}<a onClick={() => navigate('/login')} style={{ color: 'var(--accent)', cursor: 'pointer', margin: '0 6px' }}>{t("教师工作台")}</a>
          ·
          <a onClick={() => navigate('/student/login')} style={{ color: 'var(--accent)', cursor: 'pointer', margin: '0 6px' }}>{t("学生选科")}</a>
        </div>
      </div>
    </div>
  )
}