import assert from 'node:assert/strict'
import test from 'node:test'
import { groupRoster } from './roster-groups.ts'

const students = [
  { student_id: 1, student_name: '张明', class_name: '高一（10）班' },
  { student_id: 2, student_name: '李明', class_name: '高一（2）班' },
  { student_id: 3, student_name: '王芳', class_name: '高一（2）班' },
  { student_id: 4, student_name: '赵明', class_name: null },
]

test('groups by administrative class with numeric ordering and accurate totals', () => {
  const groups = groupRoster(students)
  assert.deepEqual(groups.map(g => [g.name, g.total, g.members.length]), [
    ['高一（2）班', 2, 2], ['高一（10）班', 1, 1], ['未分班', 1, 1],
  ])
  assert.equal(students[0].student_id, 1)
})

test('search trims whitespace, hides unmatched groups and preserves original group totals', () => {
  const groups = groupRoster(students, ' 李明 ')
  assert.deepEqual(groups.map(g => [g.name, g.total, g.members.map(s => s.student_id)]), [
    ['高一（2）班', 2, [2]],
  ])
  assert.deepEqual(groupRoster(students, '不存在'), [])
  assert.equal(groupRoster(students, '  ').length, 3)
  assert.deepEqual(groupRoster([]), [])
})
