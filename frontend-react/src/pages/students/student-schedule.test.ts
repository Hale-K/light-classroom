import assert from 'node:assert/strict'
import test from 'node:test'
import { combineStudentSchedule } from './student-schedule.ts'

const scope = { academic_year: '2026-2027', term: '2', class_id: 717 }
const lesson = { id: 1, class_id: 717, academic_year: '2026-2027', term: '2',
  subject_id: 1, subject_name: '语文', weekday: 1, period: 1, week_parity: 'odd' as const }
const walk = { id: 1, teaching_class_id: 590, teaching_class_name: '化学走班01',
  academic_year: '2026-2027', term: '2', subject_id: 2, subject_name: '化学',
  teacher_id: 710, teacher_name: '王老师', room: '教室11', weekday: 1, period: 8 }

test('个人课表合并行政课和走班课，保留教师、教室和单双周', () => {
  const entries = combineStudentSchedule([lesson], [walk], scope)
  assert.equal(entries.length, 2)
  assert.equal(entries[0].week_parity, 'odd')
  assert.equal(entries[1].week_parity, 'all')
  assert.equal(entries[1].teacher_name, '王老师')
  assert.equal(entries[1].room, '教室11')
  assert.equal(entries[1].class_name, '走班 · 化学走班01')
  assert.notEqual(entries[0].id, entries[1].id)
})

test('只展示当前学年学期和该学生行政班，不混入其他班或历史课程', () => {
  const entries = combineStudentSchedule([
    lesson, { ...lesson, class_id: 718 }, { ...lesson, term: '1' },
    { ...lesson, academic_year: '2025-2026' },
  ], [walk, { ...walk, term: '1' }, { ...walk, academic_year: '2025-2026' }], scope)
  assert.equal(entries.length, 2)
})

test('未分行政班不展示其他班公共课，空课表保持为空', () => {
  assert.deepEqual(combineStudentSchedule([lesson], [], { ...scope, class_id: null }), [])
  assert.deepEqual(combineStudentSchedule([], [], scope), [])
})
