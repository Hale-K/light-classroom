import { useEffect, useMemo, useState } from 'react'
import { App, Button, Card, Divider, Dropdown, Form, Input, InputNumber, Modal, Radio, Select, Space, Switch, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { aiProviderApi, type AiProvider, type AiProviderForm } from '@/api'
import FilterCard from '@/components/FilterCard'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import EmptyState from '@/components/EmptyState'

const PROVIDER_PRESETS = [
  { value: 'JEV', label: 'Jev 决策模型', defaultBaseUrl: 'https://api.typesafe.ai/v1', helpUrl: 'https://www.jevtypesafeai.com/', helpLabel: '查看 Jev 说明', keyOptional: false },
  { value: 'OLLAMA', label: 'Ollama（本地）', defaultBaseUrl: 'http://127.0.0.1:11434', helpUrl: 'https://docs.ollama.com/windows', helpLabel: '查看 Ollama 安装说明', keyOptional: true },
  { value: 'OPENAI', label: 'OpenAI', defaultBaseUrl: 'https://api.openai.com/v1', helpUrl: 'https://platform.openai.com/api-keys' },
  { value: 'DEEPSEEK', label: 'DeepSeek', defaultBaseUrl: 'https://api.deepseek.com/v1', helpUrl: 'https://platform.deepseek.com/api_keys' },
  { value: 'MOONSHOT', label: 'Kimi (Moonshot)', defaultBaseUrl: 'https://api.moonshot.cn/v1', helpUrl: 'https://platform.moonshot.cn/console/api-keys' },
  { value: 'SILICONFLOW', label: '硅基流动 SiliconFlow', defaultBaseUrl: 'https://api.siliconflow.cn/v1', helpUrl: 'https://cloud.siliconflow.cn/account/ak' },
  { value: 'ZHIPU', label: '智谱 GLM', defaultBaseUrl: 'https://open.bigmodel.cn/api/paas/v4', helpUrl: 'https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys' },
  { value: 'HUNYUAN', label: '腾讯混元', defaultBaseUrl: 'https://api.hunyuan.cloud.tencent.com/v1', helpUrl: 'https://console.cloud.tencent.com/hunyuan/api-key' },
  { value: 'JIMENG', label: '即梦（火山方舟）', defaultBaseUrl: 'https://ark.cn-beijing.volces.com/api/v3', helpUrl: 'https://jimeng.jianying.com/ai-tool/jimeng-api/console/guide', helpLabel: '查看即梦 API 指南' },
]

const MODEL_CATEGORIES = [
  { key: 'CHAT', label: '对话模型', field: 'chat_model' as const },
  { key: 'DECISION', label: '决策模型', field: 'chat_model' as const },
  { key: 'VISION', label: '视觉模型', field: 'vision_model' as const },
  { key: 'IMAGE', label: '图片模型', field: 'image_model' as const },
  { key: 'VIDEO', label: '视频模型', field: 'video_model' as const },
  { key: 'AUDIO', label: '音频模型', field: 'audio_model' as const },
]

type CategoryKey = (typeof MODEL_CATEGORIES)[number]['key']
type ModelOptions = { value: string; label: string }[]
type Categorized = Partial<Record<CategoryKey, ModelOptions>>

function categorizeModels(ids: string[]): Categorized {
  const out: Categorized = {}
  ids.forEach((id) => {
    const lower = id.toLowerCase()
    let key: CategoryKey = 'CHAT'
    if (/[_-]?(vision|visual|multimodal)/.test(lower) || /v$/.test(lower)) key = 'VISION'
    else if (/(image|img|dall-e)/.test(lower)) key = 'IMAGE'
    else if (/(video|veo|sora)/.test(lower)) key = 'VIDEO'
    else if (/(audio|tts|asr|voic|whisper)/.test(lower)) key = 'AUDIO'
    out[key] = [...(out[key] ?? []), { value: id, label: id }]
  })
  return out
}

function normalizeProviderBase(providerType: string, baseUrl: string) {
  const base = baseUrl.trim().replace(/\/$/, '')
  return providerType === 'JEV' && !base.endsWith('/v1') ? `${base}/v1` : base
}

const TYPE_LABEL: Record<string, string> = Object.fromEntries(PROVIDER_PRESETS.map((p) => [p.value, p.label]))

export default function AiProvidersView() {
  const { message, modal } = App.useApp()
  const [rows, setRows] = useState<AiProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [status, setStatus] = useState<number | undefined>()
  const [activeCategory, setActiveCategory] = useState<string>('CHAT')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<AiProvider | null>(null)
  const [saving, setSaving] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [modelOptions, setModelOptions] = useState<Categorized>({})
  const [form] = Form.useForm<AiProviderForm & { is_default: boolean }>()
  const selectedProviderType = Form.useWatch('provider_type', form)
  const selectedProvider = PROVIDER_PRESETS.find((item) => item.value === selectedProviderType)

  const load = async () => {
    setLoading(true)
    try {
      setRows(await aiProviderApi.list({ keyword: keyword || undefined, status }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => {
    const cat = MODEL_CATEGORIES.find((c) => c.key === activeCategory)
    if (!cat) return rows
    if (cat.key === 'DECISION') return rows.filter((r) => r.provider_type === 'JEV')
    if (activeCategory !== 'CHAT') return rows.filter((r) => r.provider_type !== 'JEV' && Boolean(r[cat.field]))
    return rows.filter((r) => r.provider_type !== 'JEV' && Boolean(r[cat.field]))
  }, [rows, activeCategory])

  const openEdit = (row?: AiProvider) => {
    setEditing(row ?? null)
    const preset = PROVIDER_PRESETS.find((item) => item.value === 'OLLAMA')!
    form.setFieldsValue(
      row
        ? {
            name: row.name,
            provider_type: row.provider_type,
            base_url: normalizeProviderBase(row.provider_type, row.base_url),
            chat_model: row.chat_model ?? undefined,
            vision_model: row.vision_model ?? undefined,
            image_model: row.image_model ?? undefined,
            video_model: row.video_model ?? undefined,
            audio_model: row.audio_model ?? undefined,
            timeout_seconds: row.timeout_seconds,
            is_default: row.is_default,
            status: row.status,
            sort: row.sort,
            remark: row.remark ?? undefined,
            api_key: undefined,
          }
        : {
            provider_type: preset.value,
            base_url: preset.defaultBaseUrl,
            timeout_seconds: 120,
            is_default: false,
            status: 1,
            sort: 0,
          },
    )
    if (row) {
      const stored: Partial<Record<CategoryKey, string | null | undefined>> = {
        CHAT: row.chat_model,
        VISION: row.vision_model,
        IMAGE: row.image_model,
        VIDEO: row.video_model,
        AUDIO: row.audio_model,
      }
      const categorized: Categorized = {}
      MODEL_CATEGORIES.forEach((c) => {
        const v = stored[c.key]
        if (v) categorized[c.key] = [{ value: v, label: v }]
      })
      if (row.provider_type === 'JEV' && row.chat_model) {
        categorized.DECISION = [{ value: row.chat_model, label: row.chat_model }]
      }
      setModelOptions(categorized)
    } else {
      setModelOptions({ CHAT: [] })
    }
    setOpen(true)
  }

  const save = async (values: AiProviderForm & { is_default: boolean }) => {
    if (values.provider_type === 'JEV' && !values.chat_model?.trim()) {
      message.warning('请先加载并选择 Jev 决策模型')
      return
    }
    setSaving(true)
    try {
      const payload: AiProviderForm = { ...values, status: values.status ?? 1 }
      if (editing) await aiProviderApi.update(editing.id, payload)
      else await aiProviderApi.create(payload)
      message.success('保存成功')
      setOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const loadModels = async () => {
    const { provider_type, base_url, api_key } = form.getFieldsValue()
    if (!base_url) {
      message.warning('请先填写 Base URL')
      return
    }
    setLoadingModels(true)
    try {
      const ids = await aiProviderApi.loadModels({ provider_type, base_url, api_key })
      const categorized = categorizeModels(ids)
      if (provider_type === 'JEV') categorized.DECISION = categorized.CHAT ?? []
      setModelOptions(categorized)
      if (!form.getFieldValue('chat_model') && categorized.CHAT?.[0]) {
        form.setFieldValue('chat_model', categorized.CHAT[0].value)
      }
      message.success(`已加载 ${ids.length} 个模型`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载模型失败')
    } finally {
      setLoadingModels(false)
    }
  }

  const columns: ColumnsType<AiProvider> = [
    {
      title: '服务商',
      dataIndex: 'name',
      render: (name, row) => (
        <Space>
          <strong>{name}</strong>
          {row.is_default ? <Tag color="gold">默认</Tag> : null}
        </Space>
      ),
    },
    { title: '类型', dataIndex: 'provider_type', width: 160, render: (v: string) => TYPE_LABEL[v] || v },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    {
      title: '模型',
      width: 240,
      render: (_, r) => [r.chat_model, r.vision_model, r.image_model, r.video_model, r.audio_model].filter(Boolean).join(' / ') || '—',
    },
    {
      title: '连通性',
      dataIndex: 'last_test_status',
      width: 100,
      render: (s: number | null) => (s == null ? '未测试' : s === 1 ? <Tag color="green">通</Tag> : <Tag color="red">不通</Tag>),
    },
    {
      title: '状态',
      width: 90,
      render: (_, r) => (
        <Switch size="small" checked={r.status === 1} onChange={(checked) => {
          void aiProviderApi.updateStatus(r.id, checked ? 1 : 0).then(load).catch((error) => message.error(error instanceof Error ? error.message : '更新失败'))
        }} />
      ),
    },
    {
      title: '操作',
      width: 220,
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Button type="link" size="small" loading={testingId === r.id} onClick={async () => {
            setTestingId(r.id)
            try {
              const ok = await aiProviderApi.test(r.id)
              message[ok ? 'success' : 'error'](ok ? '连接测试成功' : '连接测试失败')
              await load()
            } catch (error) {
              message.error(error instanceof Error ? error.message : '测试失败')
            } finally {
              setTestingId(null)
            }
          }}>测试</Button>
          <Dropdown
            menu={{
              items: [
                ...(!r.is_default ? [{ key: 'default', label: '设为默认' }] : []),
                { key: 'del', label: '删除', danger: true },
              ],
              onClick: ({ key }) => {
                if (key === 'default') {
                  void aiProviderApi.setDefault(r.id).then(() => { message.success('已设为默认'); return load() })
                }
                if (key === 'del') {
                  modal.confirm({
                    title: `删除服务商「${r.name}」`,
                    content: '删除后不可恢复。',
                    okText: '删除',
                    okButtonProps: { danger: true },
                    onOk: () => aiProviderApi.remove(r.id).then(() => { message.success('已删除'); return load() }),
                  })
                }
              },
            }}
          >
            <Button type="link" size="small">更多</Button>
          </Dropdown>
        </Space>
      ),
    },
  ]

  return (
    <div className="zh-page">
      <PageHeader title="服务商管理" extra={<Button type="primary" onClick={() => openEdit()}>新增服务商</Button>} />
      <p className="zh-page-desc">给学校助手配置大模型。密钥只写不读，测试连通后再设为默认。</p>
      <Tabs
        activeKey={activeCategory}
        onChange={setActiveCategory}
        items={MODEL_CATEGORIES.map((c) => ({ key: c.key, label: c.label }))}
      />
      {activeCategory === 'DECISION' && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space direction="vertical" size={4}>
            <strong>决策模型降级策略</strong>
            <span style={{ color: '#667085' }}>Jev 未配置、调用失败或置信度不足时，系统自动回退到 pgvector 和本地默认 Router。</span>
            <Tag color="blue">默认安全策略：不影响现有助手流程</Tag>
          </Space>
        </Card>
      )}
      <FilterCard>
        <Form layout="inline">
          <Form.Item label="关键词">
            <Input allowClear placeholder="名称 / Base URL" style={{ width: 220 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
          </Form.Item>
          <Form.Item label="状态">
            <Select allowClear placeholder="全部" style={{ width: 120 }} value={status} onChange={setStatus} options={[{ value: 1, label: '启用' }, { value: 0, label: '停用' }]} />
          </Form.Item>
          <Button type="primary" onClick={() => void load()}>查询</Button>
          <Button onClick={() => { setKeyword(''); setStatus(undefined); void aiProviderApi.list().then(setRows) }}>重置</Button>
        </Form>
      </FilterCard>
      <TableCard title="服务商列表">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={filtered}
          loading={loading}
          pagination={{ pageSize: 10, showTotal: (t) => `共 ${t} 个` }}
          locale={{ emptyText: <EmptyState icon="cloud" title={activeCategory === 'DECISION' ? '还没有决策模型' : '还没有服务商'} desc={activeCategory === 'DECISION' ? '新增 Jev 后，Router 才会在配置的置信度范围内使用它。未配置时自动使用默认路由。' : '新增后，助手对话会走默认启用的对话模型。'} height={240} /> }}
        />
      </TableCard>
      <Modal title={editing ? '编辑服务商' : '新增服务商'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={saving} width={720} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={save}>
          <Tabs
            tabPosition="left"
            items={[
              {
                key: 'conn',
                label: '连接信息',
                children: (
                  <>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                      <Form.Item name="name" label="服务商名称" rules={[{ required: true, message: '请输入名称' }]}>
                        <Input placeholder="如：DeepSeek / 混元" />
                      </Form.Item>
                      <Form.Item name="provider_type" label="服务商类型" rules={[{ required: true }]}>
                        <Select
                          options={PROVIDER_PRESETS.map((p) => ({ value: p.value, label: p.label }))}
                          onChange={(value) => {
                            const preset = PROVIDER_PRESETS.find((p) => p.value === value)
                            if (preset) {
                              form.setFieldValue('base_url', preset.defaultBaseUrl)
                              message.success(`已填入 ${preset.defaultBaseUrl}`)
                            }
                          }}
                        />
                      </Form.Item>
                    </div>
                    <Form.Item name="base_url" label="Base URL" extra="选类型会带默认地址，不对再改" rules={[{ required: true }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item
                      name="api_key"
                      label="API Key"
                      extra={
                        <Space size={4} wrap>
                          <span>{editing ? '留空表示不改原密钥' : selectedProvider?.keyOptional ? '本地 Ollama 不需要 API Key' : '云端服务商需要 API Key'}</span>
                          {selectedProvider?.helpUrl ? (
                            <Button
                              type="link"
                              size="small"
                              href={selectedProvider.helpUrl}
                              target="_blank"
                              rel="noreferrer"
                              style={{ padding: 0, height: 'auto' }}
                            >
                              {selectedProvider.helpLabel || `获取 ${selectedProvider.label} API Key`}
                            </Button>
                          ) : null}
                        </Space>
                      }
                    >
                      <Input.Password autoComplete="new-password" placeholder={editing ? '已保存，留空不改动' : '输入 API Key'} />
                    </Form.Item>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, padding: '8px 12px', border: '1px dashed #d9d9d9', borderRadius: 6, background: '#fafafa' }}>
                      <span style={{ color: '#8c8c8c', fontSize: 13 }}>填好 Key 后加载模型，再到右侧能力 Tab 选择</span>
                      <Button onClick={() => void loadModels()} loading={loadingModels}>加载模型</Button>
                    </div>
                    <Divider orientation="left" plain>参数</Divider>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
                      <Form.Item name="timeout_seconds" label="超时(秒)"><InputNumber min={1} max={600} style={{ width: '100%' }} /></Form.Item>
                      <Form.Item name="sort" label="排序"><InputNumber style={{ width: '100%' }} /></Form.Item>
                      <Form.Item name="status" label="状态"><Radio.Group><Radio value={1}>启用</Radio><Radio value={0}>停用</Radio></Radio.Group></Form.Item>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                      <Form.Item name="is_default" label="设为默认" valuePropName="checked"><Switch /></Form.Item>
                      <Form.Item name="remark" label="备注"><Input /></Form.Item>
                    </div>
                  </>
                ),
              },
              ...MODEL_CATEGORIES.filter((c) => (modelOptions[c.key] ?? []).length > 0).map((c) => ({
                key: c.key,
                label: c.label,
                children: (
                  <Form.Item name={c.field} label={c.label} extra="加载模型后从下拉选择，也可手填">
                    <Select showSearch allowClear placeholder="选择或输入" options={modelOptions[c.key] ?? []} />
                  </Form.Item>
                ),
              })),
            ]}
          />
        </Form>
      </Modal>
    </div>
  )
}
