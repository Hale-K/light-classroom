import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('./task.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source.replace(/^import[^\n]*\n/gm, ''), {
  compilerOptions: { module: ts.ModuleKind.ESNext },
})

async function withWatcher(t, readRun) {
  const originalFetch = globalThis.fetch
  const originalSetTimeout = globalThis.setTimeout
  const originalNow = Date.now
  const clock = { now: 0 }
  let calls = 0
  globalThis.fetch = async () => { throw new Error('SSE unavailable for this test') }
  globalThis.setTimeout = callback => originalSetTimeout(callback, 0)
  Date.now = () => clock.now
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.setTimeout = originalSetTimeout
    Date.now = originalNow
    delete globalThis.__assistantWatchFixture
  })
  globalThis.__assistantWatchFixture = {
    assistantApi: { readRun: async id => { calls++; return readRun(id, clock, calls) } },
    ApiError: class extends Error {}, getAuthHeaders: () => ({}), getSseApiBaseURL: () => 'http://test',
  }
  const code = `const {assistantApi,ApiError,getAuthHeaders,getSseApiBaseURL}=globalThis.__assistantWatchFixture;\n${outputText}`
  const module = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}#${t.name}`)
  return { watch: module.watchAssistantRun, calls: () => calls }
}

test('a ten-minute task stays observable past five minutes without resubmitting', async t => {
  const { watch, calls } = await withWatcher(t, (id, clock, count) => {
    assert.equal(id, 'same-run')
    clock.now += count === 1 ? 301000 : count === 2 ? 299000 : 1
    return { id, status: count === 3 ? 'done' : 'running', events: [], message: '处理中' }
  })
  const observed = []
  const result = await watch('same-run', new AbortController().signal, run => observed.push(run.status), () => {})
  assert.equal(result.status, 'done')
  assert.deepEqual(observed, ['running', 'running', 'done'])
  assert.equal(calls(), 3)
})

test('viewing beyond the delivery allowance retains the run rather than sending a new task', async t => {
  const { watch, calls } = await withWatcher(t, (id, clock) => {
    clock.now = 611000
    return { id, status: 'running', events: [], message: '处理中' }
  })
  await assert.rejects(watch('same-run', new AbortController().signal, () => {}, () => {}), /恢复查看/)
  assert.equal(calls(), 1)
})

test('a cancelled run is terminal and viewing cancellation does not restart it', async t => {
  const { watch, calls } = await withWatcher(t, id => ({ id, status: 'cancelled', events: [] }))
  const result = await watch('same-run', new AbortController().signal, () => {}, () => {})
  assert.equal(result.status, 'cancelled')
  assert.equal(calls(), 1)
})
