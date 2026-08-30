import assert from 'node:assert/strict'
import test from 'node:test'
import { computeSubjectStaff } from './staffing-math.ts'

const base = {
  weeklyPeriods: 5,
  classCount: 38,
  current: 0,
  available: 25,
  maxWeeklyPeriods: 20,
}

test('建议人数只按总课时除以教师周课时上限计算', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文' })
  assert.equal(r.totalPeriods, 190)
  assert.equal(r.byWorkload, Math.ceil(190 / 20))
  assert.equal(r.recommended, 10)
  assert.equal(r.shortage, 0)
})

test('班主任人数不影响学科教师的课时测算', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文' })
  assert.equal(r.recommended, 10)
})

test('教师周课时上限越低,按工作量所需人数越多', () => {
  const r = computeSubjectStaff({ ...base, subject: '数学', maxWeeklyPeriods: 10 })
  assert.equal(r.byWorkload, 19)
  assert.equal(r.recommended, 19)
})

test('体育课也按总课时估算教师人数', () => {
  const r = computeSubjectStaff({ ...base, subject: '体育', weeklyPeriods: 1, available: 13 })
  assert.equal(r.totalPeriods, 38)
  assert.equal(r.recommended, 2)
})

test('缺少:全校可用不足时 shortage = 建议 − 可用', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文', available: 8 })
  assert.equal(r.recommended, 10)
  assert.equal(r.shortage, 2, '10 − 8 = 2,按钮应禁用')
})

test('调整建议:相对当前人数的补/释放', () => {
  const r1 = computeSubjectStaff({ ...base, subject: '语文', current: 10 })
  assert.equal(r1.adjustment, 0, '建议 10、当前 10 → 保持不变')
  const r2 = computeSubjectStaff({ ...base, subject: '语文', current: 15 })
  assert.equal(r2.adjustment, -5, '建议 10、当前 15 → 释放 5')
})

test('教师周课时上限低于单班课时仍按总课时计算', () => {
  const r = computeSubjectStaff({ ...base, subject: '物理', weeklyPeriods: 3, maxWeeklyPeriods: 2 })
  assert.equal(r.recommended, 57)
})
