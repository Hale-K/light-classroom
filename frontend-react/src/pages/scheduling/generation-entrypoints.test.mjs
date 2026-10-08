import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const admin = readFileSync(new URL('./index.tsx', import.meta.url), 'utf8')
const walk = readFileSync(new URL('./WalkSchedulePanel.tsx', import.meta.url), 'utf8')

test('joint scheduling removes both standalone generation menus', () => {
  assert.doesNotMatch(admin, /单独生成行政课表/)
  assert.doesNotMatch(walk, /单独生成走班课表|高级操作仅重排/)
})

test('standalone buttons remain available only outside joint scheduling', () => {
  assert.match(admin, /\{!jointSupported && <Button[\s\S]*?onClick=\{openGenerationRulePreview\}/)
  assert.match(walk, /\{!jointSupported && <Button[\s\S]*?onClick=\{confirmGenerate\}/)
})

test('walk timetable directs joint-mode users to the shared preview and save flow', () => {
  assert.match(walk, /联合排课.*行政课和走班课.*预览.*确认保存/)
})

test('generation status, diagnostics and both timetable views remain available', () => {
  for (const label of ['排课诊断', '总体进度', '生成进度', '课表生成完成', '联合课表已保存']) {
    assert.ok(admin.includes(label), `${label} should remain available`)
  }
  assert.ok(admin.includes('<WalkSchedulePanel'))
  assert.ok(admin.includes('<ScheduleGrid'))
  assert.ok(walk.includes('<Table<WalkScheduleRow>'))
})
