import assert from 'node:assert/strict'
import test from 'node:test'
import { jumpLabel, placeLabel, samePlace } from './place.ts'

test('placeLabel reads scheduling tab', () => {
  assert.equal(placeLabel('/scheduling?tab=hours'), '排课 · 课时管理')
  assert.equal(placeLabel('/scheduling?tab=rules'), '排课 · 规则组')
  assert.equal(placeLabel('/scheduling'), '排课管理')
  assert.equal(placeLabel('/campus-buildings'), '空间资源')
})

test('samePlace treats scheduling tab as the place', () => {
  assert.equal(samePlace('/scheduling?tab=hours', '/scheduling?tab=hours'), true)
  assert.equal(samePlace('/scheduling?tab=hours', '/scheduling?tab=rules'), false)
  assert.equal(jumpLabel('/scheduling?tab=rules'), '跳转到「排课 · 规则组」')
})
