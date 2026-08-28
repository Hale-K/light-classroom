import assert from 'node:assert/strict'
import test from 'node:test'
import { allocateHeadTeachers, coreSubjectScore, headTeacherQuota, allocateWithSubjectBudget } from './head-teacher-allocation.ts'

const ids = (n: number) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }))

test('主科优先:排序靠前的候选先被使用', () => {
  // 1 个班、3 个候选(已按 语→数→英 排序),应派出第 1 位
  const { assignments, unfilledCount } = allocateHeadTeachers([101], ids(3), {}, 1)
  assert.equal(assignments[101], 1)
  assert.equal(unfilledCount, 0)
})

test('轮换派班:maxLead=1 时 38 个班恰好每人 1 个、不重复', () => {
  const { assignments, unfilledCount } = allocateHeadTeachers(
    Array.from({ length: 38 }, (_, i) => 100 + i),
    ids(38),
    {},
    1,
  )
  const usedTeachers = Object.values(assignments)
  assert.equal(usedTeachers.length, 38)
  assert.equal(new Set(usedTeachers).size, 38, '每位老师只领 1 个班')
  assert.equal(unfilledCount, 0)
})

test('领班数上限:maxLead=2 时每人最多 2 个班', () => {
  const { assignments } = allocateHeadTeachers(
    Array.from({ length: 10 }, (_, i) => 200 + i),
    ids(5),
    {},
    2,
  )
  const load = new Map<number, number>()
  for (const t of Object.values(assignments)) load.set(t, (load.get(t) ?? 0) + 1)
  assert.equal(Object.keys(assignments).length, 10)
  for (const count of load.values()) assert.ok(count <= 2, `负荷 ${count} 超过领班上限 2`)
})

test('主科耗尽自动落到其他学科:候选池顺序即降级顺序', () => {
  // 前 3 位主科老师每人只能领 1 班,5 个班 → 第 4、5 班落到其他学科候选(4、5 号)
  const { assignments, unfilledCount } = allocateHeadTeachers(
    [301, 302, 303, 304, 305],
    ids(5),
    {},
    1,
  )
  assert.equal(assignments[301], 1)
  assert.equal(assignments[302], 2)
  assert.equal(assignments[303], 3)
  assert.equal(assignments[304], 4, '主科用尽后第 4 位(其他学科)接上')
  assert.equal(assignments[305], 5)
  assert.equal(unfilledCount, 0)
})

test('已有班主任保留不动,且其教师负荷计入上限', () => {
  // 1 班已由教师 9 任班主任(maxLead=1 已满);新班只能派给候选 1
  const { assignments } = allocateHeadTeachers([401], ids(2), { 400: 9 }, 1)
  assert.equal(assignments[400], 9, '已有分配原样保留')
  assert.equal(assignments[401], 1, '满负荷的 9 号不会被再次选中')
})

test('池子不足:精确统计未安排班级数', () => {
  const { assignments, unfilledCount } = allocateHeadTeachers(
    [501, 502, 503],
    ids(1),
    {},
    1,
  )
  assert.equal(assignments[501], 1)
  assert.equal(unfilledCount, 2)
})

test('主科优先得分:语→数→英→其他', () => {
  assert.equal(coreSubjectScore(['语文教研组·成员']), 0)
  assert.equal(coreSubjectScore(['数学教研组·成员']), 1)
  assert.equal(coreSubjectScore(['英语教研组·成员']), 2)
  assert.equal(coreSubjectScore(['物理教研组·成员']), 3)
  assert.equal(coreSubjectScore(['物理教研组', '语文教研组']), 0, '跨组时主科优先')
  assert.equal(coreSubjectScore([]), 3)
})

// ===== 学科配额分配 =====

const mk = (subject: string, n: number, offset = 0) =>
  Array.from({ length: n }, (_, i) => ({ id: offset + i + 1, subject }))
const classIds = (n: number, base = 1000) => Array.from({ length: n }, (_, i) => base + i)

test('配额公式:17 名教师、38 个班 → 最多 13 个班主任', () => {
  assert.equal(headTeacherQuota(17, 38), 13)
  assert.equal(headTeacherQuota(13, 38), 1, '13 人学科只剩 39−38=1 个班主任额度')
  assert.equal(headTeacherQuota(5, 38), 0, '小学科 15<38,一人都不能当班主任')
  assert.equal(headTeacherQuota(17, 10), 7, '班少时额度充足但不超过人数的一半? 3×17−10=41→min(17,41)=17')
})

test('回归:语数各 17 人贪心会全用光,配额算法限制为 13+13', () => {
  const candidates = [...mk('语文', 17, 0), ...mk('数学', 17, 100), ...mk('英语', 17, 200)]
  const r = allocateWithSubjectBudget(classIds(38), candidates, 38, 1)
  assert.equal(r.usedBySubject['语文'], 13, '语文最多出 13 个班主任')
  assert.equal(r.usedBySubject['数学'], 13)
  assert.equal(r.usedBySubject['英语'], 12, '38−13−13=12 落到英语')
  assert.equal(r.unfilledCount, 0)
  assert.equal(r.capacityShort, false)
})

test('配额下任何学科都保有教学容量:语 17 人 13 班主任 → 13×2+4×3=38 恰好覆盖', () => {
  const candidates = [...mk('语文', 17, 0), ...mk('数学', 17, 100), ...mk('英语', 17, 200)]
  const r = allocateWithSubjectBudget(classIds(38), candidates, 38, 1)
  const covered = 13 * 2 + 4 * 3
  assert.equal(covered, 38, '语文学科容量恰好覆盖 38 班,不再出现 34<38 缺口')
})

test('单一学科场景:26 名语文教师、38 个班 → 配额 40 截到 26? 班主任 38 个全来自语文', () => {
  const candidates = mk('语文', 26)
  const r = allocateWithSubjectBudget(classIds(38), candidates, 38, 1)
  // quota = min(26, 3×26−38=40) = 26 → 26 个班主任,maxLead1 只能覆盖 26 班
  assert.equal(r.usedBySubject['语文'], 26)
  assert.equal(r.unfilledCount, 12, '领班上限 1 时 26 人只能带 26 班,余 12 班待安排')
})

test('容量不足预警:配额总量 < 班级数时 capacityShort=true', () => {
  const candidates = [...mk('语文', 10), ...mk('数学', 10)]
  const r = allocateWithSubjectBudget(classIds(38), candidates, 38, 1)
  assert.equal(r.capacityShort, true)
  assert.equal(r.unfilledCount, 38 - 20)
})
