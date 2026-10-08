import assert from 'node:assert/strict'
import test from 'node:test'
import { resolveScheduleClassId } from './scheduling-model.ts'

const classes = [
  { id: 101, grade_id: 1 },
  { id: 201, grade_id: 2 },
]

test('shows only the selected class when it belongs to the active grade', () => {
  assert.equal(resolveScheduleClassId(201, 2, classes), 201)
})

test('does not fall back to a class from another grade when none is selected', () => {
  assert.equal(resolveScheduleClassId(undefined, 2, classes), undefined)
})

test('hides a stale selection when it belongs to a different grade', () => {
  assert.equal(resolveScheduleClassId(101, 2, classes), undefined)
})
