import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Checkbox, Form, Input, Modal, Select, Space, Table, Typography, message } from 'antd'
import { useAuthStore } from '@/store/auth'
import { excelRequest, executeExcelItem, takeExcel, type ExcelItem, type ExcelPlan } from '@/assistant/excelAgent'

const kindNames = { subject: '科目', hours: '班级课时', assignment: '任课关系', rule: '排课规则' }
const statusNames = { ready: '待执行', blocked: '需修正', exists: '已有相同配置', done: '已保存', failed: '失败／已停止' }

export default function ExcelConfiguration() {
  const user = useAuthStore(s => s.user)
  const schoolCode = useAuthStore(s => s.schoolCode)
  const storageKey = `excel-config:${schoolCode}:${user?.id}`
  const [plan, setPlan] = useState<ExcelPlan | null>(null)
  const [items, setItems] = useState<ExcelItem[]>([])
  const itemsRef = useRef<ExcelItem[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [year, setYear] = useState('2026-2027')
  const [term, setTerm] = useState('1')
  const [className, setClassName] = useState('')
  const [distribute, setDistribute] = useState(false)
  const [cleanNames, setCleanNames] = useState(false)
  const [halfParity, setHalfParity] = useState('')
  const [defaultType, setDefaultType] = useState('')
  const [defaultEvening, setDefaultEvening] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [confirmation, setConfirmation] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState('')
  const [current, setCurrent] = useState<ExcelItem | null>(null)
  const controller = useRef<AbortController | null>(null)
  const confirming = useRef(false)
  const savePending = useRef<Promise<unknown> | null>(null)
  const saved = useRef(false)
  const [saving, setSaving] = useState(false)
  const [entryForm] = Form.useForm<Record<string, string>>()

  const updateItems = (next: ExcelItem[]) => {
    itemsRef.current = next; setItems(next)
    if (next.some(i => i.task_token)) sessionStorage.setItem(storageKey, JSON.stringify({ plan, items: next }))
  }
  const updateItem = (id: string, updates: Partial<ExcelItem>) => updateItems(itemsRef.current.map(i => i.id === id ? { ...i, ...updates } : i))
  useEffect(() => {
    controller.current?.abort()
    const uploaded = takeExcel(`${schoolCode}:${user?.id}`)
    if (uploaded) {
      setFile(uploaded); setPlan(null); setItems([]); itemsRef.current = []
      sessionStorage.removeItem(storageKey)
      setProgress(`已带入附件「${uploaded.name}」，请选择解析选项并预览。`)
      return () => { controller.current?.abort() }
    }
    try {
      const stored = sessionStorage.getItem(storageKey)
      if (stored) {
        const parsed = JSON.parse(stored)
        setPlan(parsed.plan); itemsRef.current = parsed.items; setItems(parsed.items)
        setProgress('已恢复上次批次；继续前需再次确认，保存结果会重新核对。')
      } else { setPlan(null); setItems([]); itemsRef.current = [] }
    } catch { sessionStorage.removeItem(storageKey) }
    return () => { controller.current?.abort() }
  }, [storageKey])

  const invalidate = () => { setPlan(null); setReviewed(false); setError(''); setItems([]); itemsRef.current = []; sessionStorage.removeItem(storageKey) }
  const preview = async () => {
    if (!file) return
    setReading(true); invalidate()
    const form = new FormData()
    form.append('file', file)
    for (const [key, value] of Object.entries({ academic_year: year, term, selected_class: className,
      distribute: String(distribute), clean_names: String(cleanNames), half_parity: halfParity,
      default_type: defaultType, default_evening: defaultEvening })) form.append(key, value)
    try {
      const result = await excelRequest<ExcelPlan>('preview', form)
      setPlan(result); itemsRef.current = result.items; setItems(result.items)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setReading(false) }
  }

  const run = async (confirmedItems: ExcelItem[]) => {
    const abort = new AbortController(); controller.current = abort
    setBusy(true); setError(''); setConfirmation(false)
    updateItems(confirmedItems)
    try {
      for (const item of confirmedItems) {
        abort.signal.throwIfAborted()
        if (item.status === 'exists') continue
        if (!item.task_token) throw new Error('缺少二次确认授权，请重新解析')
        const status = await excelRequest<{ saved: boolean }>('status', { task_token: item.task_token }, abort.signal)
        if (status.saved) { updateItem(item.id, { status: 'done', message: '核对到已有相同配置，已跳过' }); continue }
        saved.current = false
        updateItem(item.id, { status: 'ready', message: '正在操作页面' })
        entryForm.resetFields(); setCurrent(item)
        // Wait for React to display the current modal, without pre-filling fields.
        await new Promise<void>((resolve, reject) => {
          const deadline = Date.now() + 10000
          const check = () => {
            if (abort.signal.aborted) { reject(new Error('已停止')); return }
            if (document.querySelector(`[data-excel-agent-form="${item.id}"]`)) { resolve(); return }
            if (Date.now() > deadline) { reject(new Error('配置窗口未能打开')); return }
            window.setTimeout(check, 50)
          }; check()
        })
        try {
          await executeExcelItem(item, abort.signal, setProgress, () => saved.current && !savePending.current)
          if (savePending.current) await savePending.current
          const status = await excelRequest<{ saved: boolean }>('status', { task_token: item.task_token })
          if (!status.saved) throw new Error(abort.signal.aborted ? '已停止，当前项尚未保存' : '未查到保存结果，请检查模型和表单')
          updateItem(item.id, { status: 'done', message: '页面保存完成，已核对业务数据' })
        } catch (e) {
          if (savePending.current) await savePending.current.catch(() => undefined)
          const status = await excelRequest<{ saved: boolean }>('status', { task_token: item.task_token }).catch(() => null)
          updateItem(item.id, status?.saved ? { status: 'done', message: '停止前保存已完成，已核对' }
            : { status: 'failed', message: e instanceof Error ? e.message : String(e) })
          throw e
        }
        setCurrent(null)
      }
      setProgress('批次完成，已核对每项保存结果。')
    } catch (e) { setError(e instanceof Error ? e.message : '操作已停止'); setProgress('批次已停止；已保存项保留，继续前需再次确认。') }
    finally { setBusy(false); setCurrent(null); controller.current = null }
  }

  const confirm = async () => {
    if (!plan || confirming.current || controller.current) return
    confirming.current = true
    setBusy(true)
    setConfirmation(false)
    try {
      // Resume uses already issued, signed item tasks, but always asks again in UI.
      const result = items.some(i => i.task_token)
        ? { items: itemsRef.current }
        : await excelRequest<{ items: ExcelItem[] }>('confirm', { plan_token: plan.plan_token, confirmed: true })
      await run(result.items)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { confirming.current = false; setBusy(false) }
  }

  const save = async (values: Record<string, string>) => {
    if (!current || saved.current || saving || controller.current?.signal.aborted) return
    saved.current = true; setSaving(true)
    const pending = excelRequest('save', { task_token: current.task_token, values })
    savePending.current = pending
    try { await pending; void message.success('本项已保存') }
    catch (e) { saved.current = false; void message.error(e instanceof Error ? e.message : String(e)) }
    finally { savePending.current = null; setSaving(false) }
  }

  const blocked = items.some(i => i.status === 'blocked')
  const remaining = items.filter(i => !['exists', 'done'].includes(i.status)).length
  return <div style={{ padding: 24, maxWidth: 1400, margin: 'auto' }}>
    <Typography.Title level={2}>Excel配置助手</Typography.Title>
    <Alert type="info" showIcon message="上传只生成预览。核对后点击开始，再进行二次确认，Agent才会逐项操作页面保存。已有不同配置不会覆盖。" />
    <Card title="1. 上传并解析" style={{ marginTop: 16 }}>
      <Space wrap>
        <input aria-label="上传Excel" type="file" accept=".xlsx,.csv" disabled={busy || reading} onChange={e => { invalidate(); setFile(e.target.files?.[0] ?? null) }} />
        {file && <span>已选文件：{file.name}</span>}
        <a href={`${import.meta.env.BASE_URL}templates/scheduling-configuration.xlsx`} download="轻课堂排课配置模板.xlsx">下载标准模板</a>
        <Input aria-label="学年" value={year} disabled={busy || reading} style={{ width: 140 }} onChange={e => { invalidate(); setYear(e.target.value) }} />
        <Select aria-label="学期" value={term} disabled={busy || reading} onChange={v => { invalidate(); setTerm(v) }} options={[{ value: '1', label: '第1学期' }, { value: '2', label: '第2学期' }]} />
        <Input aria-label="仅配置班级" placeholder="仅配置班级（留空处理全部）" value={className} disabled={busy || reading} style={{ width: 250 }} onChange={e => { invalidate(); setClassName(e.target.value) }} />
      </Space>
      <Space wrap style={{ marginTop: 16 }}>
        <Checkbox checked={distribute} disabled={busy || reading} onChange={e => { invalidate(); setDistribute(e.target.checked) }}>确认教师总课时按所教班级均分</Checkbox>
        <Checkbox checked={cleanNames} disabled={busy || reading} onChange={e => { invalidate(); setCleanNames(e.target.checked) }}>姓名星号和空格仅为排版，可清除</Checkbox>
        <Select aria-label="半课时安排" placeholder="0.5课时安排（需明确）" value={halfParity || undefined} style={{ width: 210 }} disabled={busy || reading} onChange={v => { invalidate(); setHalfParity(v) }} options={['单周', '双周'].map(value => ({ value }))} />
        <Select aria-label="缺列课程类型" placeholder="新科目缺列时的类型" value={defaultType || undefined} style={{ width: 190 }} disabled={busy || reading} onChange={v => { invalidate(); setDefaultType(v) }} options={['学科课', '活动课'].map(value => ({ value }))} />
        <Select aria-label="缺列晚自习资格" placeholder="新科目缺列时的晚自习资格" value={defaultEvening || undefined} style={{ width: 230 }} disabled={busy || reading} onChange={v => { invalidate(); setDefaultEvening(v) }} options={['允许', '不允许'].map(value => ({ value }))} />
        <Button type="primary" loading={reading} disabled={!file || busy} onClick={() => void preview()}>解析并预览</Button>
      </Space>
    </Card>
    {error && <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} />}
    {plan && <Card title={`2. 核对预览 · ${plan.school_name} · ${plan.academic_year} 第${plan.term}学期`} style={{ marginTop: 16 }}>
      <Typography.Paragraph>共{items.length}项；按班级筛选排除{plan.excluded_rows}行或班级展开项。规则导入会保留原规则组，并将Excel规则组设为当前规则组。无法识别的内容需修正后重新解析。</Typography.Paragraph>
      <Table rowKey="id" dataSource={items} pagination={{ pageSize: 10 }} columns={[
        { title: '类型', render: (_, i: ExcelItem) => kindNames[i.kind] },
        { title: '来源', dataIndex: 'source' },
        { title: '配置', render: (_, i: ExcelItem) => i.fields?.map(f => `${f.label}：${f.value}`).join('；') || String(i.form.subject_name || i.form.rule_name || '') },
        { title: '状态', render: (_, i: ExcelItem) => statusNames[i.status] }, { title: '说明', dataIndex: 'message' },
      ]} />
      <Checkbox checked={reviewed} disabled={busy} onChange={e => setReviewed(e.target.checked)}>我已核对学校、学期、课时分摊、教师匹配和规则范围</Checkbox>
      <Space style={{ marginLeft: 16 }}>
        <Button type="primary" disabled={busy || !reviewed || blocked || !remaining} onClick={() => setConfirmation(true)}>开始／继续配置</Button>
        {busy && <Button danger onClick={() => { controller.current?.abort(); setProgress('已请求停止；正在核对当前保存请求。') }}>停止并接管</Button>}
      </Space>
    </Card>}
    {progress && <Alert message={progress} type="info" style={{ marginTop: 16 }} />}
    <Modal title="二次确认：执行本批配置" open={confirmation} onCancel={() => setConfirmation(false)} onOk={() => void confirm()} okText="确认创建并执行" cancelText="返回核对">
      <p>目标学校：{plan?.school_name}；{plan?.academic_year} 第{plan?.term}学期。</p>
      <p>将执行{remaining}项新增配置。已有相同项跳过，已有不同项拒绝覆盖。执行后已保存数据会保留；停止只取消后续操作。</p>
      <p>包含规则时，Excel规则组将成为当前规则组。请确认后开始。</p>
    </Modal>
    <Modal title={`页面配置 · ${current ? kindNames[current.kind] : ''}`} open={!!current} footer={null} closable={false} maskClosable={false} width={760}>
      {current && <div data-excel-agent-form={current.id}>
        <p>来源：{current.source}</p>
        <Form form={entryForm} layout="vertical" onFinish={values => void save(values)}>
          {current.fields?.map(field => <Form.Item key={field.key} name={field.key} label={field.label} rules={[{ required: true, message: '请填写已确认内容' }]}>
            {field.key === 'summary' ? <Input.TextArea aria-label={field.label} rows={6} disabled={saving || saved.current} /> : <Input aria-label={field.label} disabled={saving || saved.current} />}
          </Form.Item>)}
          <Button htmlType="submit" type="primary" loading={saving} disabled={saved.current}>保存本项</Button>
        </Form>
      </div>}
      <Button danger style={{ marginTop: 12 }} onClick={() => controller.current?.abort()}>停止并接管</Button>
    </Modal>
  </div>
}
