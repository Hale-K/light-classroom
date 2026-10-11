import { translate as t, useLocale } from '@/i18n'
import { useEffect, useRef } from 'react'
import { Form, Input } from 'antd'
import { useNavigate } from 'react-router-dom'
import './login-experience.css'

export interface LoginExperienceForm {
  phone: string
  password: string
}

interface LoginExperienceProps {
  submitting: boolean
  onSubmit: (values: LoginExperienceForm) => void
}

const VIDEO_SRC = 'https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260826_041744_63efcd78-bf7d-4039-99e2-2461e8a61903.mp4'
const VIDEO_FALLBACK = '/videos/mainframe-hero.mp4'

export default function LoginExperience({ submitting, onSubmit }: LoginExperienceProps) {
  useLocale()
  const navigate = useNavigate()
  const videoRef = useRef<HTMLVideoElement>(null)
  const targetTimeRef = useRef(0)
  const previousXRef = useRef<number | null>(null)
  const seekingRef = useRef(false)

  /* 鼠标横向移动搓洗视频进度：delta → 目标时间，seeked 后再排队下一次 seek，防刷屏 */
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const handleMouseMove = (event: MouseEvent) => {
      if (!video.duration || !Number.isFinite(video.duration)) return
      const previousX = previousXRef.current
      previousXRef.current = event.clientX
      if (previousX === null) return

      const delta = event.clientX - previousX
      const offset = (delta / Math.max(window.innerWidth, 1)) * 0.8 * video.duration
      targetTimeRef.current = Math.min(video.duration, Math.max(0, targetTimeRef.current + offset))

      if (!seekingRef.current) {
        seekingRef.current = true
        video.currentTime = targetTimeRef.current
      }
    }

    const handleMouseLeave = () => {
      previousXRef.current = null
    }

    const handleLoadedMetadata = () => {
      targetTimeRef.current = video.currentTime
    }

    const handleSeeked = () => {
      if (Math.abs(video.currentTime - targetTimeRef.current) > 0.01) {
        video.currentTime = targetTimeRef.current
        return
      }
      seekingRef.current = false
    }

    const handleError = () => {
      if (video.src !== VIDEO_FALLBACK && !video.src.endsWith(VIDEO_FALLBACK)) video.src = VIDEO_FALLBACK
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseleave', handleMouseLeave)
    video.addEventListener('loadedmetadata', handleLoadedMetadata)
    video.addEventListener('seeked', handleSeeked)
    video.addEventListener('error', handleError)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseleave', handleMouseLeave)
      video.removeEventListener('loadedmetadata', handleLoadedMetadata)
      video.removeEventListener('seeked', handleSeeked)
      video.removeEventListener('error', handleError)
    }
  }, [])

  return (
    <main className="login-experience" aria-label={t("轻课堂登录")}>
      <video ref={videoRef} className="login-experience__bg-video" aria-hidden="true" muted playsInline preload="auto" src={VIDEO_SRC} />
      <div className="login-experience__grain" aria-hidden="true" />
      <div className="login-experience__frame" aria-hidden="true"><span /><span /><span /><span /></div>

      <header className="login-experience__nav">
        <a className="login-experience__brand" href="#login-card">
          <span className="login-experience__brand-name">{t("轻课堂")}<sup>®</sup></span>
          <span className="login-experience__brand-mark">✳︎</span>
        </a>
      </header>

      <section className="login-experience__content">
        <div id="login-card" className="login-experience__card" role="group" aria-labelledby="login-form-title">
          <div className="login-experience__form-heading"><h2 id="login-form-title">{t("登录轻课堂")}</h2></div>
          <Form<LoginExperienceForm> layout="vertical" requiredMark={false} onFinish={onSubmit}>
            <Form.Item name="phone" label={t("手机号")} rules={[{ required: true, message: t("请输入手机号") }, { pattern: /^1\d{10}$/, message: t("手机号格式不正确") }]}>
              <Input size="large" placeholder={t("请输入手机号")} maxLength={11} autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" label={t("密码")} rules={[{ required: true, message: t("请输入密码") }]}>
              <Input.Password size="large" placeholder={t("请输入密码")} autoComplete="current-password" />
            </Form.Item>
            <button type="submit" className="login-experience__submit" disabled={submitting}><span>{submitting ? t("正在进入…") : t("进入工作台")}</span><span aria-hidden="true">↗</span></button>
          </Form>
          <div className="login-experience__ends">
            <span className="is-current">{t("教师工作台")}</span>
            <a onClick={() => navigate('/admin/login')}>{t("平台超管")}</a>
            <a onClick={() => navigate('/student/login')}>{t("学生选科")}</a>
          </div>
        </div>
      </section>
    </main>
  )
}
