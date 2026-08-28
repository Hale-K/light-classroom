import assert from 'node:assert/strict'
import test from 'node:test'
import { computeSubjectStaff } from './staffing-math.ts'

const base = {
  weeklyPeriods: 5,
  classCount: 38,
  headTeachers: 0,
  current: 0,
  available: 25,
  maxClassesPerHeadTeacher: 2,
  maxClassesPerTeacher: 3,
  maxWeeklyPeriods: 20,
}

test('未排班主任:建议 = ⌈班级数 ÷ 普通教师带班数⌉ = 13', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文' })
  assert.equal(r.totalPeriods, 190)
  assert.equal(r.byWorkload, Math.ceil(190 / 20))
  assert.equal(r.byClasses, Math.ceil(38 / 3))
  assert.equal(r.recommended, 13)
  assert.equal(r.shortage, 0)
})

test('排了 13 个班主任:建议 = 13 + ⌈(38−13×2) ÷ 3⌉ = 17', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文', headTeachers: 13 })
  assert.equal(r.byClasses, 13 + Math.ceil((38 - 13 * 2) / 3))
  assert.equal(r.recommended, 17)
})

test('工作量主导:课时上限压到 10 时,按工作量 19 > 按带班 13', () => {
  const r = computeSubjectStaff({ ...base, subject: '数学', maxWeeklyPeriods: 10 })
  assert.equal(r.byWorkload, 19)
  assert.equal(r.recommended, 19)
})

test('容量受课时约束:上限 6、每班 5 节 → 每人只能带 1 班', () => {
  const r = computeSubjectStaff({ ...base, subject: '英语', maxWeeklyPeriods: 6 })
  assert.equal(r.headCapacity, 1, 'min(2, ⌊6/5⌋)=1')
  assert.equal(r.teacherCapacity, 1, 'min(3, ⌊6/5⌋)=1')
  assert.equal(r.byClasses, 38)
})

test('体育(1 节/班):班主任容量不受课时限制,建议 = max(2, 班主任+⌈剩余⌉)', () => {
  const r = computeSubjectStaff({ ...base, subject: '体育', weeklyPeriods: 1, headTeachers: 12, available: 13 })
  assert.equal(r.totalPeriods, 38)
  assert.equal(r.headCapacity, 2, 'min(2, ⌊20/1⌋)=2')
  assert.equal(r.teacherCapacity, 3, 'min(3, ⌊20/1⌋)=3')
  assert.equal(r.byClasses, 12 + Math.ceil((38 - 24) / 3))
  assert.equal(r.recommended, Math.max(2, 12 + Math.ceil(14 / 3)))
})

test('缺少:全校可用不足时 shortage = 建议 − 可用', () => {
  const r = computeSubjectStaff({ ...base, subject: '语文', headTeachers: 13, available: 15 })
  assert.equal(r.recommended, 17)
  assert.equal(r.shortage, 2, '17 − 15 = 2,按钮应禁用')
})

test('调整建议:相对当前人数的补/释放', () => {
  const r1 = computeSubjectStaff({ ...base, subject: '语文', current: 10 })
  assert.equal(r1.adjustment, 3, '建议 13、当前 10 → 补 3')
  const r2 = computeSubjectStaff({ ...base, subject: '语文', current: 15 })
  assert.equal(r2.adjustment, -2, '建议 13、当前 15 → 释放 2')
})

test('课时上限低于单班课时:容量下限保护为 1', () => {
  const r = computeSubjectStaff({ ...base, subject: '物理', weeklyPeriods: 3, maxWeeklyPeriods: 2 })
  assert.equal(r.headCapacity, 1)
  assert.equal(r.teacherCapacity, 1)
})
