import type { StaffAccount, StaffRoleCode } from '../../types/index.ts'

export type StaffOrgNodeKey = 'school' | StaffRoleCode | 'school_admin' | 'unassigned'

export interface StaffOrgNode {
  key: StaffOrgNodeKey
  title: string
  description: string
  count: number
  children: StaffOrgNode[]
}

const ORG_GROUPS: Array<{
  key: Exclude<StaffOrgNodeKey, 'school'>
  title: string
  description: string
}> = [
  { key: 'school_admin', title: '校级管理', description: '校长及学校管理员' },
  { key: 'academic_director', title: '教务管理', description: '教务、排课与考试统筹' },
  { key: 'head_teacher', title: '班级管理', description: '行政班班主任' },
  { key: 'subject_teacher', title: '学科教学', description: '承担课程教学的教师' },
  { key: 'unassigned', title: '待配置人员', description: '尚未分配岗位职责' },
]

function belongsToNode(account: StaffAccount, key: StaffOrgNodeKey): boolean {
  if (key === 'school') return true
  if (key === 'unassigned') return account.roles.length === 0
  return account.roles.includes(key)
}

export function buildStaffOrgTree(accounts: StaffAccount[], schoolName: string): StaffOrgNode {
  return {
    key: 'school',
    title: schoolName,
    description: '全校教职工',
    count: accounts.length,
    children: ORG_GROUPS.map((group) => ({
      ...group,
      count: accounts.filter((account) => belongsToNode(account, group.key)).length,
      children: [],
    })),
  }
}

export function filterStaffByOrgNode(
  accounts: StaffAccount[],
  key: StaffOrgNodeKey,
): StaffAccount[] {
  return accounts.filter((account) => belongsToNode(account, key))
}
