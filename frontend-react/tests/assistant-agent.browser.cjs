// Run against Vite with Playwright available in NODE_PATH. Uses isolated browser/API fixtures.
const { chromium } = require('playwright')
const assert = require('node:assert/strict')

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const errors = []
    page.on('pageerror', error => { errors.push(error.message); console.error(error.message) })
    page.on('response', response => { if (response.status() >= 400) console.error(response.status(), response.url()) })
    const html = `<!doctype html><html><body><div id="root"></div><script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type; window.__vite_plugin_react_preamble_installed__ = true;
      await import('/tests/assistant-agent.harness.tsx');
    </script></body></html>`
    await page.route('**/__assistant_agent_test', route => route.fulfill({ contentType: 'text/html', body: html }))
    const plan = { id: 'fixture-plan', status: 'pending', summary: '2026 第1学期 · 高一规则\n新增 1 条白天规则（每周生效）：\n• 数学 · 科目禁排：周三 第6、7节；硬约束', expires_at: new Date(Date.now() + 1200000).toISOString() }
    let chatCalls = 0
    let decisions = []
    let conflict = false
    let slow = false
    let lastId
    const runs = new Map()
    await page.route('**/api/v1/assistant/runs', async route => {
      chatCalls++
      const body = route.request().postDataJSON()
      assert(body.messages.length <= 20)
      lastId = body.request_id
      const run = { id: lastId, status: slow ? 'running' : 'done', phase: 'tool', message: '正在查询本校规则组', elapsed_seconds: 18, phase_elapsed_seconds: 16, heartbeat_at: new Date().toISOString(), events: [{ message: '正在查询本校规则组', phase: 'tool' }], result: { text: '请核对规则草稿。', plan } }
      runs.set(lastId, run)
      await route.fulfill({ json: { code: 0, data: run } })
    })
    await page.route('**/api/v1/assistant/runs/*', async route => {
      const id = route.request().url().split('/').pop()
      await route.fulfill({ json: { code: 0, data: runs.get(id) } })
    })
    await page.route('**/api/v1/assistant/runs/*/cancel', async route => {
      const id = route.request().url().split('/').at(-2)
      const run = runs.get(id)
      run.status = 'cancelled'; run.message = '本轮已停止，未执行规则写入。'; run.result = null
      await route.fulfill({ json: { code: 0, data: run } })
    })
    await page.route('**/api/v1/assistant/actions/*', async route => {
      const body = route.request().postDataJSON()
      decisions.push(body.decision)
      assert.deepEqual(Object.keys(body), ['decision'])
      if (conflict) return route.fulfill({ status: 409, json: { detail: '规则组已被修改，请重新预览' } })
      await route.fulfill({ json: { code: 0, data: { ...plan, status: body.decision === 'confirm' ? 'executed' : 'cancelled', result: body.decision === 'confirm' ? { text: '已向高一规则保存 1 条规则。', count: 1, path: '/scheduling?tab=rules' } : null } } })
    })
    async function draft() {
      await page.goto('http://127.0.0.1:5176/__assistant_agent_test')
      await page.getByTitle('轻课堂助手', { exact: true }).click()
      await page.locator('textarea').fill('帮我添加规则：数学周三第6、7节不能排课，硬约束')
      await page.getByRole('button', { name: '发送', exact: true }).click()
      await page.getByRole('button', { name: '确认保存规则' }).waitFor()
    }
    await draft()
    assert.equal(decisions.length, 0, 'Preview must not execute')
    await page.getByRole('button', { name: '确认保存规则' }).click()
    await page.getByText('规则已保存', { exact: true }).waitFor()
    assert.deepEqual(decisions, ['confirm'])
    assert.equal(await page.getByRole('button', { name: '确认保存规则' }).count(), 0)
    await draft()
    await page.getByRole('button', { name: '取消草稿' }).click()
    await page.getByText('草稿已取消', { exact: true }).waitFor()
    assert.deepEqual(decisions, ['confirm', 'cancel'])
    await draft()
    conflict = true
    await page.getByRole('button', { name: '确认保存规则' }).click()
    await page.getByRole('alert').filter({ hasText: '重新预览' }).waitFor()
    assert.equal(await page.getByText('规则已保存', { exact: true }).count(), 0)
    await page.locator('textarea').fill('改成周四')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.waitForFunction(() => document.querySelectorAll('.assist-rule-plan').length === 2)
    assert.equal(chatCalls, 4, 'Follow-up must stay in agent conversation')
    await page.setViewportSize({ width: 390, height: 844 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
    assert.equal(overflow, false, 'Mobile page must not overflow')
    slow = true
    await page.getByRole('button', { name: '新对话', exact: true }).last().click()
    await page.locator('textarea').fill('帮我检查本校排课准备情况，还缺什么？')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByText('后台仍在响应', { exact: true }).waitFor()
    await page.getByText('当前阶段暂未返回新结果。你可以继续使用其他页面，或停止本轮处理。', { exact: true }).waitFor()
    const beforeReload = chatCalls
    await page.reload()
    await page.getByText('后台仍在响应', { exact: true }).waitFor()
    assert.equal(chatCalls, beforeReload, 'Reload must recover without submitting again')
    await page.getByRole('button', { name: '停止', exact: true }).click()
    await page.getByText('本轮已停止，未执行规则写入。', { exact: false }).waitFor()
    assert.equal(runs.get(lastId).status, 'cancelled')
    assert.deepEqual(errors, [])
    console.log('PASS: preview, confirm, cancel, conflict, follow-up, mobile layout, live progress, reload recovery, task cancellation; no browser errors')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
