import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('./activity.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { activityLines, restoreActivity, restoreExecution, executionModeLabel, executionStatusLabel } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('shows real tool and update events in order, never internal reasoning', () => {
  assert.deepEqual(activityLines([
    { phase: 'preparing', message: '准备' },
    { phase: 'trace', visibility: 'internal', message: 'secret reasoning' },
    { phase: 'tool', message: '正在查询课时' },
    { phase: 'observed', message: '查询已返回' },
    { phase: 'observed', message: '查询已返回' },
    { phase: 'model', message: '等待模型' },
  ]), [{ kind: 'tool', text: '正在查询课时' }, { kind: 'update', text: '查询已返回' }])
})

test('empty or model-only events do not invent completed queries', () => {
  assert.deepEqual(activityLines([{ phase: 'model', message: '等待模型' }]), [])
  assert.deepEqual(activityLines([]), [])
})

test('restoring saved milestones validates shape and excludes traces', () => {
  assert.deepEqual(restoreActivity([{ kind: 'trace', text: 'secret' }, null, { kind: 'tool', text: '查询课时' }]), [{ kind: 'tool', text: '查询课时' }])
  assert.deepEqual(restoreActivity('invalid'), [])
})

test('the public mode labels have exactly two meanings and migrate saved legacy runs', () => {
  assert.equal(executionModeLabel('query'), '普通问答/查询')
  assert.equal(executionModeLabel('planning'), '复杂规划/执行')
  assert.equal(executionModeLabel('pending'), '')
  assert.equal(restoreExecution({ mode: 'direct', tasks: [] }).mode, 'query')
  assert.equal(restoreExecution({ mode: 'agent', tasks: [] }).mode, 'query')
  assert.equal(restoreExecution({ mode: 'supervisor', tasks: [] }).mode, 'planning')
  assert.equal(restoreExecution({ mode: 'unknown', tasks: [] }), undefined)
})

test('restored planning progress keeps waiting and failed steps, rejects private fields', () => {
  const execution = restoreExecution({ mode: 'planning', goal: '三个课时方案', tasks: [
    { id: 'environment', label: '读取环境', status: 'completed', summary: '已核对40节', raw_response: 'private' },
    { id: 'plan', label: '生成方案', status: 'running' },
    { id: 'verify', label: '方案校验', status: 'pending' },
    { id: 'retry', label: '恢复查询', status: 'timed_out' },
    { id: 'missing', label: '补充范围', status: 'blocked', summary: '需要目标年级' },
  ] })
  assert.equal(execution.goal, '三个课时方案')
  assert.deepEqual(execution.tasks.map(task => task.status), ['succeeded', 'running', 'pending', 'timed_out', 'blocked'])
  assert.equal(execution.tasks[0].summary, '已核对40节')
  assert.equal(JSON.stringify(execution).includes('private'), false)
  assert.equal(executionStatusLabel('pending'), '待执行')
  assert.equal(executionStatusLabel('timed_out'), '超时')
  assert.equal(executionStatusLabel('completed'), '完成')
  assert.equal(executionStatusLabel('blocked'), '待补充')
})

test('planning milestones are visible while internal planning data stays hidden', () => {
  assert.deepEqual(activityLines([
    { phase: 'planning', message: '计划已更新' },
    { phase: 'checking', message: '正在核对三个方案' },
    { phase: 'planning', visibility: 'internal', message: 'private reasoning' },
  ]), [{ kind: 'update', text: '计划已更新' }, { kind: 'update', text: '正在核对三个方案' }])
})
