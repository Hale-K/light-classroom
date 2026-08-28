import assert from 'node:assert/strict'
import test from 'node:test'
import type { OrganizationUnit } from '../../types/index.ts'
import { organizationExpandedKeys } from './tree-utils.ts'

const unit = (id: number, children: OrganizationUnit[] = []): OrganizationUnit => ({
  id, parent_id: null, name: `组织${id}`, unit_type: 'department', academic_year: null,
  cohort_label: null, sort_order: id, status: 'active', member_count: 0, children,
})

test('异步加载组织树后展开学校和全部组织节点', () => {
  assert.deepEqual(organizationExpandedKeys([unit(1, [unit(2, [unit(3)])])]), ['school', 1, 2, 3])
})
