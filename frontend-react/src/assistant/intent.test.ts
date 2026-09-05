import assert from 'node:assert/strict'
import test from 'node:test'
import { classifyTeacherIntent, parsePrepSlots } from './intent.ts'

const PASTE = `排课要求：
1.各科课程备课时间（备课时段不排相应课程）：
语文 星期一：6、7节 
英语 星期二：6、7节 
数学 星期三：6、7节 
物理 星期二：3、4节 
化学 星期五：3、4节 
生物 星期四：3、4节 
政治 星期三：4、5节 
历史 星期五：6、7节 
地理 星期四：6、7节`

test('paste is prep forbidden not full rule pack', () => {
  const intent = classifyTeacherIntent(PASTE)
  assert.equal(intent.name, 'prep_forbidden')
  if (intent.name !== 'prep_forbidden') return
  assert.equal(intent.slots.length, 9)
  assert.deepEqual(intent.slots[0], { subject: '语文', weekday: '周一', periods: [6, 7] })
  assert.deepEqual(intent.slots[3], { subject: '物理', weekday: '周二', periods: [3, 4] })
  assert.deepEqual(intent.slots[8], { subject: '地理', weekday: '周四', periods: [6, 7] })
})

test('parse weekday 星期N', () => {
  assert.deepEqual(parsePrepSlots('语文 星期一：6、7节'), [{ subject: '语文', weekday: '周一', periods: [6, 7] }])
})

test('21条 is rule pack', () => {
  assert.equal(classifyTeacherIntent('这些规则怎么配，21条').name, 'rule_pack')
})

test('math consecutive is not llm', () => {
  const intent = classifyTeacherIntent('数学周一到周五为6课时，其中有一天必须连着上课')
  assert.equal(intent.name, 'consecutive')
  if (intent.name !== 'consecutive') return
  assert.equal(intent.hint.subject, '数学')
  assert.equal(intent.hint.weekly, 6)
})

test('备课时间 without rows uses school default nine', () => {
  const intent = classifyTeacherIntent('备课时间怎么配')
  assert.equal(intent.name, 'prep_forbidden')
  if (intent.name !== 'prep_forbidden') return
  assert.equal(intent.slots.length, 9)
})

test('homeroom fifth period uses teacher slot forbidden', () => {
  const intent = classifyTeacherIntent('我想添加一个班主任不能排第五节，怎么设置')
  assert.equal(intent.name, 'rule_add')
  if (intent.name !== 'rule_add') return
  assert.equal(intent.guide.template, '教师课位禁排')
  assert.equal(intent.guide.target, '班主任')
  assert.equal(intent.guide.periods, '第5节')
})
