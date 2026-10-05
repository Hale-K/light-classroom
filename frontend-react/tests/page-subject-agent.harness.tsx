// Isolated demo: real AssistantDock, subject form and PageAgent; fixture APIs
// never read or write school data and never call a paid model.
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { App, ConfigProvider } from 'antd'
import { http } from '../src/api/http'
import AssistantDock from '../src/components/AssistantDock'
import SubjectManagementView from '../src/pages/subjects'
import type { SubjectDraft } from '../src/assistant/subjectTask'
import { validateFixture } from './page-subject-fixture'

const subjects = [{ id: 1, tenant_id: 1, name: '数学', course_type: 'subject', evening_study_allowed: false }]
let prepared: SubjectDraft | null = null
let saves = 0
let modelCalls = 0
let modelStep = 0
let mode = 'success'
let conversation: unknown[] = []
const nativeFetch = window.fetch.bind(window)

http.defaults.adapter = async config => {
  let data: unknown = {}
  if (config.url === '/scheduling/subjects') {
    if (config.method === 'post') {
      const values = JSON.parse(config.data)
      saves++
      subjects.push({ ...values, id: subjects.length + 1, tenant_id: 1 })
      data = subjects.at(-1)
    } else data = subjects
  } else if (config.url === '/assistant/conversation') {
    if (config.method === 'put') conversation = JSON.parse(config.data).messages
    else if (config.method === 'delete') conversation = []
    data = { messages: conversation }
  }
  return { data: { code: 0, data }, status: 200, statusText: 'OK', headers: {}, config }
}

window.fetch = async (input, init) => {
  const url = String(input)
  if (!url.includes('/page-agent/')) return nativeFetch(input, init)
  init?.signal?.throwIfAborted()
  const body = JSON.parse(String(init?.body || '{}'))
  if (url.endsWith('/subjects/prepare')) {
    if (mode === 'prepare-failure') {
      mode = 'success'
      return Response.json({ detail: '演示：首次科目校验失败，请补充课程类型和晚自习资格。' }, { status: 422 })
    }
    const result = validateFixture(body.content, body.draft, subjects.map(subject => subject.name))
    if (result.status === 'ready') { prepared = result.draft; modelStep = 0 }
    return Response.json({ code: 0, data: { ...result, task_token: 'fixture-token' } })
  }
  modelCalls++
  if (mode === 'failure') return Response.json({ detail: '演示模型服务暂时不可用' }, { status: 503 })
  if (mode === 'slow') {
    await new Promise((_resolve, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), { once: true }))
  }
  const state = body.messages.filter((message: { role: string }) => message.role === 'user').at(-1)?.content || ''
  const lineIndex = (pattern: RegExp) => {
    const line = state.split('\n').find((line: string) => pattern.test(line))
    const match = line?.match(/\[(\d+)\]/)
    if (!match) throw new Error(`Fixture cannot find control: ${pattern}`)
    return Number(match[1])
  }
  const actions: Array<() => Record<string, unknown>> = [
    () => ({ click_element_by_index: { index: lineIndex(/<button.*新增科目/) } }),
    () => ({ input_text: { index: lineIndex(/<input.*例如/), text: prepared!.name } }),
  ]
  if (prepared!.course_type === 'activity') {
    actions.push(() => ({ click_element_by_index: { index: lineIndex(/<.*role=["']combobox/) } }))
    actions.push(() => ({ click_element_by_index: { index: lineIndex(/活动课/) } }))
  }
  if (prepared!.evening_study_allowed) {
    actions.push(() => ({ click_element_by_index: { index: lineIndex(/<button.*switch/) } }))
  }
  actions.push(() => ({ click_element_by_index: { index: lineIndex(/<button.*保\s*存/) } }))
  actions.push(() => ({ done: { text: '已完成', success: true } }))
  const action = mode === 'false-success' ? { done: { text: '已完成', success: true } }
    : actions[Math.min(modelStep++, actions.length - 1)]()
  return Response.json({ choices: [{ finish_reason: 'tool_calls', message: { role: 'assistant', content: null, tool_calls: [{
    id: `fixture-${modelCalls}`, type: 'function', function: {
      name: 'AgentOutput', arguments: JSON.stringify({ evaluation_previous_goal: '检查当前页面', memory: '仅新增科目', next_goal: '完成表单', action }),
    },
  }] } }], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 } })
}

function Harness() {
  return <ConfigProvider><App>
    <div style={{ padding: 24 }}>
      <h1>科目助手 · 隔离演示</h1>
      <p>使用真实页面和 Page Agent，科目与模型响应均为测试数据，不写入学校数据库。</p>
      <Link to="/tests/page-subject-agent.html">演示首页</Link>{' · '}<Link to="/subjects">科目管理</Link>
      <p><label>测试场景：<select aria-label="测试场景" onChange={event => { mode = event.target.value }}>
        <option value="success">正常操作</option><option value="failure">模型失败</option>
        <option value="prepare-failure">首次校验失败（验证草稿保留）</option>
        <option value="false-success">模型误报成功</option><option value="slow">等待模型（可停止）</option>
      </select></label></p>
      <button onClick={event => { event.currentTarget.textContent = `保存 ${saves} 次 / 模型 ${modelCalls} 次` }}>查看测试计数</button>
      <Routes><Route path="/subjects" element={<SubjectManagementView />} /><Route path="*" element={<p>打开右侧助手，输入“帮我新增一个科目”，依次补充“心理”“学科课”“不允许晚自习”。三个字段明确后才会操作。</p>} /></Routes>
    </div>
    <AssistantDock />
  </App></ConfigProvider>
}

createRoot(document.getElementById('root')!).render(<BrowserRouter><Harness /></BrowserRouter>)
