import assert from 'node:assert/strict'
import test from 'node:test'
import type { StaffAccount } from '../../types/index.ts'
import { buildStaffOrgTree, filterStaffByOrgNode } from './org-tree.ts'

const accounts: StaffAccount[] = [
  {
    id: 1,
    name: '周校长',
    phone: '13800000001',
    status: 'active',
    roles: ['school_admin'],
    is_school_admin: true,
  },
  {
    id: 2,
    name: '李主任',
    phone: '13800000002',
    status: 'active',
    roles: ['academic_director', 'subject_teacher'],
    is_school_admin: false,
  },
  {
    id: 3,
    name: '王老师',
    phone: '13800000003',
    status: 'disabled',
    roles: [],
    is_school_admin: false,
  },
]

test('组织树按职责统计人员，兼任人员可以属于多个节点', () => {
  const tree = buildStaffOrgTree(accounts, 'gaokao312')

  assert.equal(tree.count, 3)
  assert.deepEqual(
    tree.children.map((node) => [node.key, node.count]),
    [
      ['school_admin', 1],
      ['academic_director', 1],
      ['head_teacher', 0],
      ['subject_teacher', 1],
      ['unassigned', 1],
    ],
  )
})

test('点击组织节点返回对应人员，根节点返回全部人员', () => {
  assert.deepEqual(filterStaffByOrgNode(accounts, 'school_admin').map((item) => item.id), [1])
  assert.deepEqual(filterStaffByOrgNode(accounts, 'subject_teacher').map((item) => item.id), [2])
  assert.deepEqual(filterStaffByOrgNode(accounts, 'unassigned').map((item) => item.id), [3])
  assert.equal(filterStaffByOrgNode(accounts, 'school').length, 3)
})
