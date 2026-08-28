import { useEffect, useState } from 'react'
import { App } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import { selectDisplayName, useAuthStore } from '@/store/auth'
import LoginExperience from './LoginExperience'

export default function Login() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const login = useAuthStore((s) => s.login)
  const [submitting, setSubmitting] = useState(false)

  // 已登录访问登录页 → 直接进入工作台（仅挂载时判断一次）
  useEffect(() => {
    if (useAuthStore.getState().token) navigate('/dashboard', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const from = (location.state as { from?: string } | null)?.from

  const onFinish = async (values: { phone: string; password: string }) => {
    setSubmitting(true)
    try {
      await login(values.phone, values.password)
      const displayName = selectDisplayName(useAuthStore.getState())
      message.success(`欢迎回来，${displayName || '老师'}`)
      navigate(from || '/dashboard', { replace: true })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '登录失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return <LoginExperience submitting={submitting} onSubmit={onFinish} />
}
