import assert from 'node:assert/strict'
import test from 'node:test'
import { allocateHeadTeachers, coreSubjectScore } from './head-teacher-allocation.ts'

const ids = (n: number) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }))

test('候选按顺序轮换分配班主任', () => {
  const { assignments, unfilledCount } = allocateHeadTeachers([101, 102, 103], ids(2), {})
  assert.deepEqual(assignments, { 101: 1, 102: 2, 103: 1 })
  assert.equal(unfilledCount, 0)
})

test('同一教师可以担任多个班的班主任', () => {
  const { assignments, unfilledCount } = allocateHeadTeachers(
    Array.from({ length: 10 }, (_, i) => 200 + i),
    ids(2),
    {},
  )
  assert.equal(Object.keys(assignments).length, 10)
  assert.equal(new Set(Object.values(assignments)).size, 2)
  assert.equal(unfilledCount, 0)
})

test('已有班主任分配保留不动', () => {
  const { assignments } = allocateHeadTeachers([401], ids(2), { 400: 9 })
  assert.equal(assignments[400], 9)
  assert.equal(assignments[401], 1)
})

test('候选池不足时只统计未安排班级', () => {
  const { assignments, unfilledCount } = allocateHeadTeachers([501, 502, 503], [], {})
  assert.deepEqual(assignments, {})
  assert.equal(unfilledCount, 3)
})

test('主科优先得分:语→数→英→其他', () => {
  assert.equal(coreSubjectScore(['语文教研组·成员']), 0)
  assert.equal(coreSubjectScore(['数学教研组·成员']), 1)
  assert.equal(coreSubjectScore(['英语教研组·成员']), 2)
  assert.equal(coreSubjectScore(['物理教研组·成员']), 3)
})
