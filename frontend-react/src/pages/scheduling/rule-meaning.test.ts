import assert from 'node:assert/strict'
import test from 'node:test'
import { conciseRuleMeaning } from './rule-meaning.ts'

test('规则含义根据配置展示对象、动作和时间，不采用自定义名称', () => {
  assert.equal(
    conciseRuleMeaning({ target: '班会', operator: '禁止占用指定课位', time: '周五第7节' }),
    '班会：不排 · 周五第7节',
  )
})

test('班主任课位规则明确表示必须由班主任上课', () => {
  assert.equal(
    conciseRuleMeaning({ target: '全年级各班', operator: '必须安排', time: '周二第5节', requiredTeacherRole: 'head_teacher' }),
    '全年级各班：班主任上课 · 周二第5节',
  )
})

test('无已配置时间时不虚构课位', () => {
  assert.equal(conciseRuleMeaning({ target: '数学', operator: '要求连堂' }), '数学：连堂')
})
