import { useEffect, useRef } from 'react'
import { Form, Input } from 'antd'
import { APP_NAME } from '@/types'
import './login-experience.css'

export interface LoginExperienceForm {
  phone: string
  password: string
}

interface LoginExperienceProps {
  submitting: boolean
  onSubmit: (values: LoginExperienceForm) => void
}

const VIDEO_SRC = '/videos/mainframe-hero.mp4'

export default function LoginExperience({ submitting, onSubmit }: LoginExperienceProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const targetTimeRef = useRef(0)
  const previousXRef = useRef<number | null>(null)
  const seekingRef = useRef(false)
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

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseleave', handleMouseLeave)
    video.addEventListener('loadedmetadata', handleLoadedMetadata)
    video.addEventListener('seeked', handleSeeked)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseleave', handleMouseLeave)
      video.removeEventListener('loadedmetadata', handleLoadedMetadata)
      video.removeEventListener('seeked', handleSeeked)
    }
  }, [])

  return (
    <main className="login-experience" aria-label="轻课堂登录">
      <video ref={videoRef} className="login-experience__bg-video" aria-hidden="true" muted playsInline preload="auto" src={VIDEO_SRC} />
      <div className="login-experience__video-tint" aria-hidden="true" />
      <div className="login-experience__grain" aria-hidden="true" />
      <div className="login-experience__frame" aria-hidden="true"><span /><span /><span /><span /></div>

      <header className="login-experience__nav">
        <a className="login-experience__brand" href="#login-card">
          <span className="login-experience__brand-name">轻课堂<sup>®</sup></span>
          <span className="login-experience__brand-mark">✳︎</span>
        </a>
      </header>

      <section className="login-experience__content">
        <div id="login-card" className="login-experience__card" role="group" aria-labelledby="login-form-title">
          <div className="login-experience__card-topline"><span>工作台入口</span><span>// 01</span></div>
          <div className="login-experience__form-heading"><h2 id="login-form-title">登录轻课堂</h2><span>SECURE ACCESS</span></div>
          <Form<LoginExperienceForm> layout="vertical" requiredMark={false} onFinish={onSubmit}>
            <Form.Item name="phone" label="手机号" rules={[{ required: true, message: '请输入手机号' }, { pattern: /^1\d{10}$/, message: '手机号格式不正确' }]}>
              <Input size="large" placeholder="请输入手机号" maxLength={11} autoFocus autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password size="large" placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>
            <button type="submit" className="login-experience__submit" disabled={submitting}><span>{submitting ? '正在进入…' : '进入工作台'}</span><span aria-hidden="true">↗</span></button>
          </Form>
          <div className="login-experience__trust"><span><i />学校数据隔离</span><span><i />操作全程留痕</span></div>
          <p className="login-experience__card-footer">{APP_NAME} / SCHOOL ADMINISTRATION PLATFORM</p>
        </div>
      </section>

      <footer className="login-experience__footer"><span>轻课堂 · 学校教务管理平台</span><span>© 2026 LIGHTCLASS</span></footer>
    </main>
  )
}
