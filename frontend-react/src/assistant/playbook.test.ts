import assert from 'node:assert/strict'
import test from 'node:test'
import { isHowToUse, isSchedulingPageHelp } from './playbook.ts'

test('scheduling steps are howToUse', () => {
  assert.equal(isHowToUse('我想排课，请告诉我排课步骤'), true)
  assert.equal(isHowToUse('怎么排课'), true)
  assert.equal(isHowToUse('系统怎么用'), true)
  assert.equal(isHowToUse('我想排高一的课'), false)
})

test('page help is not generic howToUse', () => {
  assert.equal(isSchedulingPageHelp('这个页面怎么用'), true)
  assert.equal(isSchedulingPageHelp('我想排课，请告诉我排课步骤'), false)
})
