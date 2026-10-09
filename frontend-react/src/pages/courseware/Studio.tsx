/**
 * 课件工作台（独立全屏页，无侧栏菜单）。
 * 交互范式对齐即梦式创作画布：双击画布弹出创作菜单，输入走弹窗，
 * 画布上只放「作品」——互动课件预览节点与 AI 配图节点；生成走 SSE 流式，实时进度在作品节点内。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Form, Input, Modal, Select, Tag } from 'antd'
import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider, useNodesState } from '@xyflow/react'
import type { Node, NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { coursewareApi, generateCoursewareStream } from '@/api'
import type { CourseCatalog, GeneratedImageInfo } from '@/types'
import CourseScopeFields from './CourseScopeFields'

type AppNode = Node<Record<string, unknown>>
type CreateType = 'courseware' | 'image'

interface CoursewareNodeData extends Record<string, unknown> {
  title: string
  status: 'streaming' | 'done' | 'error'
  chars: number
  model: string
  html: string
  error: string
  onOpen: (nodeId: string) => void
  onRemove: (nodeId: string) => void
}

interface ImageNodeData extends Record<string, unknown> {
  title: string
  status: 'loading' | 'done' | 'error'
  images: GeneratedImageInfo[]
  error: string
  onRemove: (nodeId: string) => void
}

function mmss(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/* ---------- 作品节点（纯展示） ---------- */

function CoursewareArtifactNode(props: NodeProps) {
  const d = props.data as unknown as CoursewareNodeData
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    if (d.status !== 'streaming') return
    const timer = window.setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => window.clearInterval(timer)
  }, [d.status])

  return (
    <div className="cws-art cws-art-courseware">
      <div className="cws-art-head">
        <span className={`cws-dot ${d.status}`} />
        <span className="cws-art-title">{d.title || '未命名课件'}</span>
        {d.status === 'done' && <Tag color="purple" style={{ marginRight: 0 }}>已存课件库</Tag>}
        <a className="cws-art-x" onClick={() => d.onRemove(props.id)}>✕</a>
      </div>
      <div className="cws-art-body">
        {d.status === 'done' && d.html ? (
          <iframe title={d.title} srcDoc={d.html} sandbox="allow-scripts allow-popups allow-pointer-lock" className="cws-art-frame" />
        ) : d.status === 'streaming' ? (
          <div className="cws-art-empty">
            <div className="cws-orbit" />
            <p className="cws-art-line1">AI 正在编写互动课件</p>
            <p>{d.model ? `模型 ${d.model} · ` : ''}已接收 {(d.chars || 0).toLocaleString()} 字 · {mmss(elapsed)}</p>
          </div>
        ) : (
          <div className="cws-art-empty">
            <p className="cws-error">{d.error || '生成失败'}</p>
            <p className="cws-art-tip">可以再新建一个课件节点重试</p>
          </div>
        )}
      </div>
      {d.status === 'done' && (
        <div className="cws-art-foot">
          <span>知识点热点 · 选择题 · 任务清单</span>
          <Button size="small" onClick={() => d.onOpen(props.id)}>新窗口打开</Button>
        </div>
      )}
    </div>
  )
}

function ImageArtifactNode(props: NodeProps) {
  const d = props.data as unknown as ImageNodeData
  return (
    <div className="cws-art cws-art-image">
      <div className="cws-art-head">
        <span className={`cws-dot ${d.status === 'done' ? 'done' : d.status === 'error' ? 'error' : 'streaming'}`} />
        <span className="cws-art-title">{d.title || 'AI 配图'}</span>
        {d.status === 'done' && <Tag color="cyan" style={{ marginRight: 0 }}>已存课件库</Tag>}
        <a className="cws-art-x" onClick={() => d.onRemove(props.id)}>✕</a>
      </div>
      {d.status === 'done' && d.images.length > 0 ? (
        <div className="cws-img-grid">
          {d.images.map((img) => (
            <div className="cws-img-item" key={img.id}>
              <img src={img.url} alt={img.title} />
              <a onClick={() => window.open(img.url, '_blank', 'noopener')}>查看大图</a>
            </div>
          ))}
        </div>
      ) : d.status === 'loading' ? (
        <div className="cws-art-empty cws-art-empty-sm">
          <div className="cws-orbit" />
          <p>即梦生成中…</p>
        </div>
      ) : (
        <div className="cws-art-empty cws-art-empty-sm">
          <p className="cws-error">{d.error || '生成失败'}</p>
        </div>
      )}
    </div>
  )
}

const nodeTypes = { courseware: CoursewareArtifactNode, image: ImageArtifactNode }

export default function CoursewareStudio() {
  return (
    <ReactFlowProvider>
      <StudioInner />
    </ReactFlowProvider>
  )
}

function StudioInner() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [nodes, setNodes, onNodesChange] = useNodesState<AppNode>([])
  const [catalog, setCatalog] = useState<CourseCatalog | null>(null)
  const [savedCount, setSavedCount] = useState(0)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [createType, setCreateType] = useState<CreateType | null>(null)
  const [form] = Form.useForm()
  const [imgForm] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [imgBusy, setImgBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const flowPosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  const patchNode = useCallback((id: string, patch: Record<string, unknown>) => {
    setNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)))
  }, [setNodes])

  const removeNode = useCallback((id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id))
  }, [setNodes])

  const openInWindow = useCallback((id: string) => {
    setNodes((ns) => {
      const node = ns.find((n) => n.id === id)
      const html = node ? (node.data as unknown as CoursewareNodeData).html : ''
      if (html) {
        const blob = new Blob([html], { type: 'text/html' })
        window.open(URL.createObjectURL(blob), '_blank', 'noopener')
      }
      return ns
    })
  }, [setNodes])

  useEffect(() => {
    void coursewareApi.catalog().then(setCatalog).catch(() => message.error('课程目录加载失败'))
    return () => abortRef.current?.abort()
  }, [message])

  function nextPosition(): { x: number; y: number } {
    return { x: 80 + nodes.length * 56, y: 100 + nodes.length * 44 }
  }

  function handlePaneDoubleClick(e: React.MouseEvent) {
    if (!(e.target instanceof HTMLElement) || !e.target.classList.contains('react-flow__pane')) return
    setMenu({ x: e.clientX, y: e.clientY })
  }

  function pickCreate(type: CreateType, clientX?: number, clientY?: number) {
    setCreateType(type)
    setMenu(null)
    if (clientX != null && clientY != null) flowPosRef.current = { x: clientX, y: clientY }
  }

  async function submitCourseware() {
    const values = await form.validateFields()
    const id = `cw-${Date.now()}`
    setCreateType(null)
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: 'courseware',
        position: nextPosition(),
        data: {
          title: values.title, status: 'streaming', chars: 0, model: '', html: '', error: '',
          onOpen: openInWindow, onRemove: removeNode,
        },
      },
    ])
    setSubmitting(true)
    const controller = new AbortController()
    abortRef.current = controller
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
        {
          onProgress: (chars) => patchNode(id, { chars }),
          onModel: (name) => patchNode(id, { model: name }),
        },
        controller.signal,
      )
      patchNode(id, { status: 'done', html: item.html_content || '', title: item.title })
      setSavedCount((c) => c + 1)
      message.success('课件已生成并保存到课件库')
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        patchNode(id, { status: 'error', error: (err as Error).message || '生成失败' })
      }
    } finally {
      setSubmitting(false)
      abortRef.current = null
    }
  }

  async function submitImage() {
    const values = await imgForm.validateFields()
    const id = `img-${Date.now()}`
    setCreateType(null)
    setNodes((ns) => [
      ...ns,
      {
        id,
        type: 'image',
        position: nextPosition(),
        data: {
          title: `AI 配图 · ${values.prompt.slice(0, 18)}`,
          status: 'loading', images: [], error: '', onRemove: removeNode,
        },
      },
    ])
    setImgBusy(true)
    try {
      const { items } = await coursewareApi.generateImages({ prompt: values.prompt, size: values.size })
      patchNode(id, { status: 'done', images: items })
      setSavedCount((c) => c + 1)
      message.success(`已生成 ${items.length} 张配图并保存到课件库`)
    } catch (err) {
      patchNode(id, { status: 'error', error: (err as Error).message || '配图生成失败' })
    } finally {
      setImgBusy(false)
    }
  }

  return (
    <div className="cws-page">
      <header className="cws-topbar">
        <button className="cws-back" onClick={() => navigate('/courseware')}>← 课件库</button>
        <span className="cws-logo">✦</span>
        <span className="cws-title">课件工作台</span>
        <span className="cws-sub">双击画布创建 · 节点可拖拽 · 作品自动保存</span>
        <div className="cws-top-actions">
          {savedCount > 0 && <Tag color="purple">本次已保存 {savedCount}</Tag>}
          <Button size="small" onClick={() => pickCreate('courseware')}>＋ 互动课件</Button>
          <Button size="small" onClick={() => pickCreate('image')}>＋ AI 配图</Button>
        </div>
      </header>
      {/* 双击挂在捕获阶段：React Flow 的缩放控制会在冒泡阶段吃掉 pane 的 dblclick */}
      <div className="cws-body" onDoubleClickCapture={handlePaneDoubleClick}>
        <ReactFlow
          nodes={nodes}
          onNodesChange={onNodesChange}
          nodeTypes={nodeTypes}
          minZoom={0.15}
          maxZoom={1.6}
          fitView
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="#262d40" />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>

        {nodes.length === 0 && (
          <div className="cws-hint">
            <div className="cws-hint-mark">✦</div>
            <div className="cws-hint-title">双击画布，开始创作</div>
            <div className="cws-hint-sub">互动课件（可漫游、可答题）· AI 配图（即梦生成）</div>
          </div>
        )}

        {menu && (
          <>
            <div className="cws-menu-mask" onClick={() => setMenu(null)} />
            <div className="cws-menu" style={{ left: menu.x, top: menu.y }}>
              <button className="cws-menu-item" onClick={() => pickCreate('courseware', menu.x, menu.y)}>
                <span className="cws-menu-icon purple">✦</span>
                <span>
                  <strong>互动课件</strong>
                  <em>可漫游、答题、任务清单的单文件网页课件</em>
                </span>
              </button>
              <button className="cws-menu-item" onClick={() => pickCreate('image', menu.x, menu.y)}>
                <span className="cws-menu-icon cyan">◈</span>
                <span>
                  <strong>AI 配图</strong>
                  <em>即梦文生图，自动存入课件库</em>
                </span>
              </button>
            </div>
          </>
        )}

        <Modal
          title="✦ 生成互动课件"
          open={createType === 'courseware'}
          onCancel={() => { if (!submitting) setCreateType(null) }}
          onOk={() => void submitCourseware()}
          confirmLoading={submitting}
          okText={submitting ? '提交中…' : '开始生成'}
          cancelText="取消"
          width={520}
          centered
          destroyOnHidden
          maskClosable={false}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="title" label="课题" rules={[{ required: true, message: '请填写课题' }]}>
              <Input placeholder="如：太阳系漫游" allowClear />
            </Form.Item>
            <Form.Item label="试试">
              <div className="cws-chiprow">
                {['太阳系漫游', '盛唐长安西市', '光合作用探秘'].map((t) => (
                  <a className="cws-chip" key={t} onClick={() => form.setFieldsValue({ title: t })}>{t}</a>
                ))}
              </div>
            </Form.Item>
            <CourseScopeFields catalog={catalog} form={form} compact />
            <Form.Item name="requirement" label="教学要求（可选）">
              <Input.TextArea rows={3} placeholder="想强调的知识点、场景偏好（如 3D 漫游）、互动方式" />
            </Form.Item>
          </Form>
          <div className="cws-form-tip">生成约需 1-5 分钟，节点实时显示进度；完成后自动保存课件库。</div>
        </Modal>

        <Modal
          title="◈ AI 配图"
          open={createType === 'image'}
          onCancel={() => { if (!imgBusy) setCreateType(null) }}
          onOk={() => void submitImage()}
          confirmLoading={imgBusy}
          okText={imgBusy ? '生成中…' : '开始生成'}
          cancelText="取消"
          width={480}
          centered
          destroyOnHidden
          maskClosable={false}
        >
          <Form form={imgForm} layout="vertical" initialValues={{ size: '1024x1024' }}>
            <Form.Item name="prompt" label="画面描述" rules={[{ required: true, message: '描述想要的画面' }]}>
              <Input.TextArea rows={3} placeholder="如：八大行星环绕太阳运行的插画，深蓝太空背景" />
            </Form.Item>
            <Form.Item name="size" label="尺寸">
              <Select
                options={[
                  { value: '1024x1024', label: '1024 × 1024（方形）' },
                  { value: '1152x864', label: '1152 × 864（横版）' },
                  { value: '864x1152', label: '864 × 1152（竖版）' },
                ]}
              />
            </Form.Item>
          </Form>
          <div className="cws-form-tip">凭据在「服务商管理」维护（即梦 / 火山方舟），图片自动存入课件库。</div>
        </Modal>
      </div>
    </div>
  )
}
