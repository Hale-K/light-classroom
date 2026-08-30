import assert from 'node:assert/strict'
import test from 'node:test'
import { hasRoomFeature } from './room-features.ts'

test('supports array features returned by the API', () => {
  assert.equal(hasRoomFeature(['multimedia'], 'multimedia'), true)
})

test('supports object features returned by JSON columns', () => {
  assert.equal(hasRoomFeature({ multimedia: true }, 'multimedia'), true)
  assert.equal(hasRoomFeature({ feature: 'multimedia' }, 'multimedia'), true)
})

test('treats empty and invalid feature values as absent', () => {
  assert.equal(hasRoomFeature({}, 'multimedia'), false)
  assert.equal(hasRoomFeature(null, 'multimedia'), false)
  assert.equal(hasRoomFeature(undefined, 'multimedia'), false)
})
