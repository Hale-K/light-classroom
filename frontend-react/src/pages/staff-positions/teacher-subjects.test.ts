import assert from 'node:assert/strict'
import test from 'node:test'
import { diffTeacherSubjectAppointments } from './teacher-subjects.ts'

test('只同步教师的学科组任职，不影响其他组织岗位', () => {
  const result = diffTeacherSubjectAppointments(
    [
      { id: 101, staff_id: 7, organization_unit_id: 10, position_code: 'member', status: 'active' },
      { id: 102, staff_id: 7, organization_unit_id: 20, position_code: 'head_teacher', status: 'active' },
      { id: 103, staff_id: 8, organization_unit_id: 11, position_code: 'member', status: 'active' },
    ],
    7,
    [10, 11, 12],
    [11, 12],
  )

  assert.deepEqual(result, { toCreate: [11, 12], toRemove: [101] })
})
