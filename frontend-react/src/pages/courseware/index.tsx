/**
 * 课件管理：按小学到高三课程目录归档课件，
 * 支持本地上传、外部链接收藏与 AI 生成单文件互动课件（浏览器直接打开）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App, Button, Empty, Form, Input, Modal, Popconfirm, Segmented, Select, Spin } from 'antd'
import PageHeader from '@/components/PageHeader'
import { coursewareApi } from '@/api'
import type { CourseCatalog, CoursewareInfo } from '@/types'
import CourseScopeFields from './CourseScopeFields'

const TYPE_META: Record<CoursewareInfo['courseware_type'], { label: string; color: string }> = {
  file: { label: '文件', color: '#1677ff' },
  html: { label: 'AI 互动', color: '#7c3aed' },
  link: { label: '链接', color: '#0891b2' },
}

const TYPE_OPTIONS = [
  { value: 'file', label: '上传文件' },
  { value: 'html', label: 'AI 互动课件' },
  { value: 'link', label: '外部链接' },
]

function fmtSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${size} B`
}

export default function CoursewareView() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [catalog, setCatalog] = useState<CourseCatalog | null>(null)
  const [items, setItems] = useState<CoursewareInfo[]>([])
  const [loading, setLoading] = useState(true)

  // 筛选
  const [fStage, setFStage] = useState<string>()
  const [fGrade, setFGrade] = useState<string>()
  const [fSubject, setFSubject] = useState<string>()
  const [fType, setFType] = useState<string>()
  const [fKeyword, setFKeyword] = useState('')

  // 新建（上传 / 链接）
  const [createOpen, setCreateOpen] = useState(false)
  const [createMode, setCreateMode] = useState<'file' | 'link'>('file')
  const [createForm] = Form.useForm()
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // 预览（AI 互动课件）
  const [preview, setPreview] = useState<CoursewareInfo | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const stageMeta = useMemo(() => catalog?.stages.find((s) => s.name === fStage), [catalog, fStage])

  async function load(next?: { keyword?: string }) {
    setLoading(true)
    try {
      const data = await coursewareApi.list({
        stage: fStage || undefined,
        grade: fGrade || undefined,
        subject: fSubject || undefined,
        courseware_type: fType || undefined,
        keyword: (next?.keyword ?? fKeyword) || undefined,
      })
      setItems(data)
    } catch {
      message.error('课件列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void coursewareApi.catalog().then(setCatalog).catch(() => message.error('课程目录加载失败'))
  }, [message])

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fStage, fGrade, fSubject, fType])

  function openCreate() {
    setCreateMode('file')
    setUploadFile(null)
    createForm.resetFields()
    setCreateOpen(true)
  }

  async function submitCreate() {
    const values = await createForm.validateFields()
    if (createMode === 'file') {
      if (!uploadFile) {
        message.warning('请先选择要上传的课件文件')
        return
      }
      const fd = new FormData()
      fd.append('file', uploadFile)
      for (const key of ['title', 'stage', 'grade_name', 'subject_name', 'textbook_version', 'chapter', 'remark'] as const) {
        if (values[key]) fd.append(key, String(values[key]))
      }
      setSaving(true)
      try {
        await coursewareApi.upload(fd)
        message.success('课件上传成功')
        setCreateOpen(false)
        await load()
      } catch {
        message.error('上传失败，请重试')
      } finally {
        setSaving(false)
      }
    } else {
      setSaving(true)
      try {
        await coursewareApi.createLink(values)
        message.success('链接收藏成功')
        setCreateOpen(false)
        await load()
      } catch {
        message.error('收藏失败，请检查链接地址')
      } finally {
        setSaving(false)
      }
    }
  }

  async function openPreview(item: CoursewareInfo) {
    if (item.courseware_type === 'link') {
      window.open(item.source_url, '_blank', 'noopener')
      return
    }
    if (item.courseware_type === 'file') {
      try {
        const { url } = await coursewareApi.download(item.id)
        window.open(url, '_blank', 'noopener')
      } catch {
        message.error('获取下载地址失败')
      }
      return
    }
    setPreviewLoading(true)
    try {
      setPreview(await coursewareApi.detail(item.id))
    } catch {
      message.error('课件内容加载失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  async function removeItem(item: CoursewareInfo) {
    try {
      await coursewareApi.remove(item.id)
      message.success('已删除')
      await load()
    } catch {
      message.error('删除失败')
    }
  }

  const stats = useMemo(() => {
    const html = items.filter((i) => i.courseware_type === 'html').length
    const file = items.filter((i) => i.courseware_type === 'file').length
    const link = items.filter((i) => i.courseware_type === 'link').length
    return `共 ${items.length} 个课件 · AI 互动 ${html} · 文件 ${file} · 链接 ${link}`
  }, [items])

  return (
    <Spin spinning={loading || previewLoading}>
      <div className="page-container">
        <PageHeader
          title="课件管理"
          desc="覆盖小学到高三全部课程 · 支持本地上传、外部链接收藏与 AI 生成互动课件"
          extra={
            <>
              <Button onClick={openCreate}>上传课件</Button>
              <Button type="primary" onClick={() => navigate('/courseware/studio')}>
                ✦ AI 生成课件
              </Button>
            </>
          }
        />

        <div className="cw-toolbar">
          <Select
            value={fStage}
            onChange={(v) => { setFStage(v); setFGrade(undefined); setFSubject(undefined) }}
            allowClear
            placeholder="学段"
            style={{ width: 104 }}
            options={(catalog?.stages ?? []).map((s) => ({ value: s.name, label: s.name }))}
          />
          <Select
            value={fGrade}
            onChange={setFGrade}
            allowClear
            placeholder="年级"
            style={{ width: 112 }}
            options={(stageMeta?.grades ?? []).map((g) => ({ value: g, label: g }))}
          />
          <Select
            value={fSubject}
            onChange={setFSubject}
            allowClear
            placeholder="学科"
            style={{ width: 124 }}
            showSearch
            optionFilterProp="label"
            options={(stageMeta?.subjects ?? catalog?.stages.flatMap((s) => s.subjects) ?? [])
              .filter((v, i, arr) => arr.indexOf(v) === i)
              .map((s) => ({ value: s, label: s }))}
          />
          <Select value={fType} onChange={setFType} allowClear placeholder="类型" style={{ width: 128 }} options={TYPE_OPTIONS} />
          <Input.Search
            value={fKeyword}
            onChange={(e) => setFKeyword(e.target.value)}
            onSearch={(v) => void load({ keyword: v })}
            placeholder="搜索标题 / 章节 / 学科"
            allowClear
            style={{ width: 220 }}
          />
          <span className="cw-stats">{stats}</span>
        </div>

        {items.length === 0 && !loading ? (
          <Empty description="还没有课件，点击右上角「上传课件」或「AI 生成课件」开始" style={{ marginTop: 80 }} />
        ) : (
          <div className="cw-grid">
            {items.map((item) => {
              const badge = TYPE_META[item.courseware_type]
              return (
                <div className="cw-card" key={item.id}>
                  <div className="cw-head">
                    <span className={`cw-badge cw-badge-${item.courseware_type}`}>{badge?.label ?? item.courseware_type}</span>
                    <span className="cw-subject">{[item.stage, item.grade_name, item.subject_name].filter(Boolean).join(' · ') || '未归类'}</span>
                  </div>
                  <div className="cw-title" title={item.title}>{item.title}</div>
                  {item.chapter && <div className="cw-chapter" title={item.chapter}>{item.chapter}</div>}
                  <div className="cw-meta">
                    {item.textbook_version && <span className="cw-tag">{item.textbook_version}</span>}
                    {item.courseware_type === 'file' && item.file_size > 0 && (
                      <span className="cw-tag">{fmtSize(item.file_size)}</span>
                    )}
                    {(item.tags ?? []).map((t) => <span className="cw-tag" key={t}>{t}</span>)}
                  </div>
                  <div className="cw-foot">
                    <span>{item.created_by_name || '—'} · {(item.created_at || '').slice(0, 10)}</span>
                    <span style={{ marginLeft: 'auto', display: 'flex', gap: 10 }}>
                      <Button type="link" size="small" onClick={() => void openPreview(item)}>
                        {item.courseware_type === 'html' ? '预览' : '打开'}
                      </Button>
                      <Popconfirm title="确定删除这个课件吗？" onConfirm={() => void removeItem(item)} okText="删除" cancelText="取消">
                        <Button type="link" size="small" danger>删除</Button>
                      </Popconfirm>
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* 上传 / 链接收藏 */}
        <Modal
          title={createMode === 'file' ? '上传课件' : '收藏课件链接'}
          open={createOpen}
          onCancel={() => setCreateOpen(false)}
          onOk={() => void submitCreate()}
          confirmLoading={saving}
          okText={createMode === 'file' ? '上传' : '收藏'}
          cancelText="取消"
          width={520}
          centered
          destroyOnHidden
        >
          <Segmented
            value={createMode}
            onChange={(v) => setCreateMode(v as 'file' | 'link')}
            options={[{ value: 'file', label: '上传文件' }, { value: 'link', label: '收藏链接' }]}
            style={{ marginBottom: 16 }}
            block
          />
          <Form form={createForm} layout="vertical">
            <Form.Item name="title" label="课件名称" rules={[{ required: createMode === 'link', message: '请填写课件名称' }]}>
              <Input placeholder={createMode === 'file' ? '不填则使用文件名' : '如：压强 · 第一课时'} allowClear />
            </Form.Item>
            {createMode === 'file' ? (
              <Form.Item label="课件文件" required>
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  accept=".ppt,.pptx,.doc,.docx,.pdf,.xls,.xlsx,.mp4,.html,.zip,image/*"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                />
                <div className="cw-drop" onClick={() => fileRef.current?.click()}>
                  {uploadFile
                    ? `已选择：${uploadFile.name}（${fmtSize(uploadFile.size)}）`
                    : '点击选择文件（PPT / Word / PDF / 视频 / HTML / 图片，≤200MB）'}
                </div>
              </Form.Item>
            ) : (
              <Form.Item
                name="source_url"
                label="链接地址"
                rules={[
                  { required: true, message: '请填写链接' },
                  { type: 'url', message: '请填写合法的 http(s) 链接' },
                ]}
              >
                <Input placeholder="https://…" allowClear />
              </Form.Item>
            )}
            <CourseScopeFields catalog={catalog} form={createForm} />
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} placeholder="使用建议、适用班级等（可选）" />
            </Form.Item>
          </Form>
        </Modal>

        {/* 互动课件预览 */}
        <Modal
          title={preview?.title}
          open={!!preview}
          onCancel={() => setPreview(null)}
          footer={null}
          width="min(1100px, 94vw)"
          centered
          destroyOnHidden
        >
          {preview?.html_content ? (
            <iframe
              title={preview.title}
              srcDoc={preview.html_content}
              sandbox="allow-scripts allow-popups allow-pointer-lock"
              style={{ width: '100%', height: '72vh', border: 0, borderRadius: 8, background: '#fff' }}
            />
          ) : (
            <Empty description="该课件没有可预览的内容" />
          )}
        </Modal>
      </div>
    </Spin>
  )
}
