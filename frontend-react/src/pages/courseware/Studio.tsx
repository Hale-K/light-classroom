/**
 * 课件工作台：左侧生成配置，右侧实时预览；生成走 SSE 流式（进度实时可见），
 * 完成自动保存课件库；底部 AI 配图（即梦/火山方舟策略，凭据在「服务商管理」维护）。
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Form, Input, Select, Tag } from 'antd'
import { coursewareApi, generateCoursewareStream } from '@/api'
import type { CourseCatalog, CoursewareInfo, GeneratedImageInfo } from '@/types'
import CourseScopeFields from './CourseScopeFields'

type Phase = 'idle' | 'generating' | 'done'

const EXAMPLES = ['太阳系漫游', '盛唐长安西市', '光合作用探秘']

function mmss(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function CoursewareStudio() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CourseCatalog | null>(null)
  const [form] = Form.useForm()

  const [phase, setPhase] = useState<Phase>('idle')
  const [chars, setChars] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [html, setHtml] = useState('')
  const [saved, setSaved] = useState<CoursewareInfo | null>(null)
  const [errorText, setErrorText] = useState('')
  const [previewKey, setPreviewKey] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  // AI 配图
  const [imgPrompt, setImgPrompt] = useState('')
  const [imgSize, setImgSize] = useState('1024x1024')
  const [imgBusy, setImgBusy] = useState(false)
  const [images, setImages] = useState<GeneratedImageInfo[]>([])

  useEffect(() => {
    void coursewareApi.catalog().then(setCatalog).catch(() => message.error('课程目录加载失败'))
  }, [message])

  useEffect(() => {
    if (phase !== 'generating') return
    const timer = window.setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  async function startGenerate() {
    const values = await form.validateFields()
    const controller = new AbortController()
    abortRef.current = controller
    setPhase('generating')
    setChars(0)
    setElapsed(0)
    setHtml('')
    setSaved(null)
    setErrorText('')
    try {
      const item = await generateCoursewareStream(
        {
          title: values.title,
          stage: values.stage ?? '',
          grade_name: values.grade_name ?? '',
          subject_name: values.subject_name ?? '',
          textbook_version: values.textbook_version,
          chapter: values.chapter,
          requirement: values.requirement,
        },
        (n) => setChars(n),
        controller.signal,
      )
      setHtml(item.html_content || '')
      setSaved(item)
      setPhase('done')
      message.success('课件已生成并保存到课件库')
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        setPhase('idle')
        return
      }
      setErrorText((err as Error).message || '生成失败，请稍后重试')
      setPhase('idle')
    } finally {
      abortRef.current = null
    }
  }

  function stopGenerate() {
    abortRef.current?.abort()
  }

  function openInWindow() {
    const blob = new Blob([html], { type: 'text/html' })
    window.open(URL.createObjectURL(blob), '_blank', 'noopener')
  }

  async function generateImages() {
    if (!imgPrompt.trim()) {
      message.warning('先描述想要的配图内容')
      return
    }
    setImgBusy(true)
    try {
      const { items } = await coursewareApi.generateImages({ prompt: imgPrompt, size: imgSize })
      setImages((prev) => [...items, ...prev])
      message.success(`已生成 ${items.length} 张配图并保存到课件库`)
    } catch (err) {
      message.error((err as Error).message || '配图生成失败')
    } finally {
      setImgBusy(false)
    }
  }

  const progressPct = `${Math.min(95, Math.round(chars / 400))}%`

  return (
    <div className="page-container">
      <div className="cw-studio">
        <aside className="cw-studio-side">
          <div className="cw-studio-side-head">
            <button className="cw-back" onClick={() => navigate('/courseware')}>← 课件库</button>
            <div className="cw-studio-title">✦ AI 课件工作台</div>
          </div>
          <Form form={form} layout="vertical" className="cw-studio-form">
            <Form.Item name="title" label="课题" rules={[{ required: true, message: '请填写课题' }]}>
              <Input placeholder="如：太阳系漫游" allowClear />
            </Form.Item>
            <CourseScopeFields catalog={catalog} form={form} compact />
            <Form.Item name="requirement" label="教学要求（可选）">
              <Input.TextArea rows={3} placeholder="想强调的知识点、场景偏好（如 3D 漫游）、互动方式等" />
            </Form.Item>
          </Form>
          <div className="cw-examples">
            <span>试试：</span>
            {EXAMPLES.map((t) => (
              <a key={t} onClick={() => form.setFieldsValue({ title: t })}>{t}</a>
            ))}
          </div>
          {phase === 'generating' ? (
            <div className="cw-gen-status">
              <div className="cw-gen-bar"><span style={{ width: progressPct }} /></div>
              <div>正在生成 · 已接收 {chars.toLocaleString()} 字 · {mmss(elapsed)}</div>
              <Button size="small" onClick={stopGenerate}>停止</Button>
            </div>
          ) : (
            <Button type="primary" block size="large" onClick={() => void startGenerate()}>
              ✦ 开始生成
            </Button>
          )}
          <div className="cw-gen-tip">
            生成约需 1-5 分钟，完成后自动保存到课件库。模型在「服务商管理」配置。
          </div>
        </aside>

        <main className="cw-studio-main">
          <div className="cw-studio-toolbar">
            <div className="cw-studio-doc">
              {saved ? saved.title : phase === 'generating' ? '生成中…' : '尚未生成课件'}
              {saved && <Tag color="purple">已保存</Tag>}
            </div>
            <div className="cw-studio-actions">
              {html && <Button size="small" onClick={() => setPreviewKey((k) => k + 1)}>刷新预览</Button>}
              {html && <Button size="small" onClick={openInWindow}>新窗口打开</Button>}
            </div>
          </div>
          <div className="cw-studio-canvas">
            {phase === 'done' && html ? (
              <iframe
                key={previewKey}
                title={saved?.title || '课件预览'}
                srcDoc={html}
                sandbox="allow-scripts allow-popups allow-pointer-lock"
                className="cw-studio-frame"
              />
            ) : phase === 'generating' ? (
              <div className="cw-studio-empty">
                <div className="cw-orbit" />
                <p>
                  正在按你的配置撰写互动课件…
                  <br />
                  已接收 {chars.toLocaleString()} 字 · {mmss(elapsed)}
                </p>
              </div>
            ) : (
              <div className="cw-studio-empty">
                <h3>从一个课题开始</h3>
                <p>填写左侧配置并点击「✦ 开始生成」，这里会实时呈现可交互的课件。</p>
                {errorText && <p className="cw-error">{errorText}</p>}
              </div>
            )}
          </div>
          <div className="cw-image-panel">
            <div className="cw-image-head">
              <strong>AI 配图</strong>
              <span>即梦 · 自动存入课件库</span>
              <Select
                size="small"
                value={imgSize}
                onChange={setImgSize}
                style={{ width: 116 }}
                options={[
                  { value: '1024x1024', label: '1024 × 1024' },
                  { value: '1152x864', label: '1152 × 864' },
                  { value: '864x1152', label: '864 × 1152' },
                ]}
              />
            </div>
            <div className="cw-image-row">
              <Input
                value={imgPrompt}
                onChange={(e) => setImgPrompt(e.target.value)}
                onPressEnter={() => void generateImages()}
                placeholder="描述配图，如：八大行星环绕太阳运行的插画"
                allowClear
              />
              <Button type="primary" loading={imgBusy} onClick={() => void generateImages()}>生成</Button>
            </div>
            {images.length > 0 && (
              <div className="cw-image-grid">
                {images.map((img) => (
                  <div className="cw-image-item" key={img.id}>
                    <img src={img.url} alt={img.title} />
                    <a onClick={() => window.open(img.url, '_blank', 'noopener')}>查看大图</a>
                  </div>
                ))}
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  )
}
