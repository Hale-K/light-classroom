import test from 'node:test'
import assert from 'node:assert/strict'
import { unavailableAt } from './availability.ts'

test('Wednesday afternoon is blocked by overlapping time, not session numbering', () => {
  const rules = ['weekly#3#13:00#18:00']
  assert(unavailableAt(rules, '2026-06-10', '14:30', '16:30', 99))
  assert(unavailableAt(rules, '2026-06-10', '12:30', '13:30', 1))
  assert(!unavailableAt(rules, '2026-06-10', '09:00', '11:00', 1))
  assert(!unavailableAt(rules, '2026-06-11', '14:30', '16:30', 1))
  assert(!unavailableAt(rules, '2026-06-10', '18:00', '19:00', 1))
  assert(unavailableAt(['2026-06-10#1'], '2026-06-10', '09:00', '11:00', 1))
})
