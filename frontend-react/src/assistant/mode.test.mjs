import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('./mode.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { modeForTurn, canUsePageActions } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('the submitted turn keeps its mode even if the composer subsequently changes', () => {
  assert.equal(modeForTurn([{ role: 'user', assistantMode: 'plan' }], 'standard'), 'plan')
  assert.equal(modeForTurn([{ role: 'user', assistantMode: 'standard' }], 'plan'), 'standard')
})

test('old messages use current composer mode and plan turns cannot use page actions', () => {
  assert.equal(modeForTurn([{ role: 'user' }], 'plan'), 'plan')
  assert.equal(canUsePageActions('plan'), false)
  assert.equal(canUsePageActions('standard'), true)
})
