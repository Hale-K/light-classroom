import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('./materials.ts', import.meta.url), 'utf8')
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText
const { mergeMaterials, materialsForTurn } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`)
const one = { id: 'one', name: 'a.txt', text: '课时', truncated: false }

test('selected materials deduplicate and preserve file text', () => {
  assert.deepEqual(mergeMaterials([one], [one]), [one])
  assert.equal(mergeMaterials([], [one])[0].text, '课时')
})
test('count and combined content bounds are enforced', () => {
  assert.throws(() => mergeMaterials([], Array.from({ length: 9 }, (_, i) => ({ ...one, id: String(i) }))), /8/)
  assert.throws(() => mergeMaterials([], [one, { ...one, id: 'two', text: '课'.repeat(24000) }]), /24000/)
})
test('a later follow-up keeps the most recent material context without duplicating it', () => {
  const turns = [{ role: 'user', text: '核对文件', materials: [one] }, { role: 'bot', text: '已读取' }, { role: 'user', text: '再看一下' }]
  assert.deepEqual(materialsForTurn(turns), [one])
  assert.deepEqual(materialsForTurn([...turns, { role: 'user', text: '新的文件', materials: [] }]), [])
})
