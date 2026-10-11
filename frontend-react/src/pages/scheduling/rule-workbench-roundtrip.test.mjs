import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'
import { ruleWeekParity } from './rule-workbench-checks.ts'

const source = await readFile(new URL('./RuleGroupWorkbench.tsx', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source + '\nexport { hydrateGroupFromApi };', {
  compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
})
// Exercise the actual conversion functions without mounting the UI or calling APIs.
globalThis.__ruleRoundtripParity = ruleWeekParity
const code = 'const ruleWeekParity = globalThis.__ruleRoundtripParity;\n' + outputText.replace(/^import[^\n]*\n/gm, '')
const { hydrateGroupFromApi, toApiRuleGroup } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
delete globalThis.__ruleRoundtripParity

test('preset teacher ban IDs preserve saved per-day slots through load and save', () => {
  const resources = { teachers: [{ id: 702, name: '毛宇莹' }], subjects: [], classes: [], assignments: [] }
  const specific = [{ weekday: 1, periods: [1, 3] }, { weekday: 2, periods: [5, 8] }]
  for (const id of ['R12', 'custom-ban']) {
    const saved = { id: 'group', name: '测试', academic_year: '2026-2027', term: '2', rules: [{
      id, title: '毛宇莹不可用课位', code: 'teacher_forbidden_slots', enabled: true, priority: 'hard',
      target: { type: 'teacher', ids: [702] }, weekdays: [], periods: [], period_scope: 'regular',
      week_parity: 'odd', schedule_scope: 'all', params: { forbidden_slots: specific },
    }] }
    const restored = hydrateGroupFromApi(saved, resources)
    const result = toApiRuleGroup(restored, saved.academic_year, saved.term, resources).rules.find(r => r.id === id)
    assert.equal(result.code, 'teacher_forbidden_slots')
    assert.deepEqual(result.params.forbidden_slots, specific)
    assert.deepEqual(result.target.ids, [702])
    assert.equal(result.week_parity, 'odd')
  }
})
