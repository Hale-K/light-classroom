/** 班主任批量分配算法(纯函数,供行政班管理与测试使用)。

策略:候选按序轮派——每人先填满领班数上限再轮到下一位;
主科优先通过候选列表的排序体现(语→数→英→其他),主科耗尽自然落到其他学科。
*/

export interface HeadTeacherCandidate {
  id: number
}

export interface HeadTeacherAllocationResult {
  /** classId -> teacherId 的完整分配(含已有班主任的班) */
  assignments: Record<number, number>
  /** 池子耗尽后仍没排到班主任的班级数 */
  unfilledCount: number
}

export function allocateHeadTeachers(
  /** 待安排的班级 ID(不含已设班主任的班) */
  pendingClassIds: number[],
  /** 已按优先级排好序的候选教师 */
  candidates: HeadTeacherCandidate[],
  /** 已有分配 classId -> teacherId(保留不动,其教师负荷计入) */
  existing: Record<number, number>,
  /** 每位教师最多领几个班 */
  maxLead: number,
): HeadTeacherAllocationResult {
  const assignments = { ...existing }
  const currentLoad = new Map<number, number>()
  for (const teacherId of Object.values(existing)) {
    currentLoad.set(teacherId, (currentLoad.get(teacherId) ?? 0) + 1)
  }
  const pool = [...candidates]
  let unfilledCount = 0
  for (const classId of pendingClassIds) {
    const index = pool.findIndex((teacher) => (currentLoad.get(teacher.id) ?? 0) < maxLead)
    const candidate = index >= 0 ? pool[index] : undefined
    if (!candidate) {
      unfilledCount += 1
      continue
    }
    assignments[classId] = candidate.id
    currentLoad.set(candidate.id, (currentLoad.get(candidate.id) ?? 0) + 1)
    // 轮换:派过一位后移到队尾,下一位候选先上,避免连续占满同一人
    pool.push(...pool.splice(index, 1))
  }
  return { assignments, unfilledCount }
}

/** 主科优先得分:语 0 → 数 1 → 英 2 → 其他 3(用于候选排序) */
export function coreSubjectScore(subjectNames: string[]): number {
  if (subjectNames.some((name) => name.includes('语文'))) return 0
  if (subjectNames.some((name) => name.includes('数学'))) return 1
  if (subjectNames.some((name) => name.includes('英语'))) return 2
  return 3
}

/** 某学科最多能出多少个班主任,才不挤占该科教学容量。

数学关系:该科 N 名教师中 h 人当班主任后,最大可覆盖班级数
  = headCap × h + teacherCap × (N − h)
  = teacherCap × N − h        (headCap = teacherCap − 1 时)
要 ≥ classCount → h ≤ teacherCap × N − classCount。
例:N=17、班主任带 2、普通带 3、38 个班 → h ≤ 51−38 = 13。
*/
export function headTeacherQuota(teacherCount: number, classCount: number, headCap = 2, teacherCap = 3): number {
  const span = Math.max(1, teacherCap - headCap)
  return Math.max(0, Math.min(teacherCount, Math.floor((teacherCap * teacherCount - classCount) / span)))
}

export interface SubjectBudgetCandidate {
  id: number
  subject: string
}

export interface BudgetAllocationResult {
  assignments: Record<number, number>
  /** 每学科实际派出多少班主任 */
  usedBySubject: Record<string, number>
  /** 按学科配额算完后仍没排到的班级数 */
  unfilledCount: number
  /** 配额总量不足以覆盖全部班级时为 true(需扩师资或上调带班数) */
  capacityShort: boolean
}

/** 按学科配额分配班主任:先算每科最多出几个班主任(保住该科普通教师带班容量),
 *  再按主科优先+科内轮转逐班派发。防止"语→数→英贪心"把单一学科教师全变成班主任。 */
export function allocateWithSubjectBudget(
  pendingClassIds: number[],
  candidates: SubjectBudgetCandidate[],
  classCount: number,
  maxLead = 1,
  headCap = 2,
  teacherCap = 3,
): BudgetAllocationResult {
  const bySubject = new Map<string, SubjectBudgetCandidate[]>()
  for (const c of candidates) {
    if (!bySubject.has(c.subject)) bySubject.set(c.subject, [])
    bySubject.get(c.subject)!.push(c)
  }
  const quota: Record<string, number> = {}
  const used: Record<string, number> = {}
  const order = [...bySubject.keys()].sort((a, b) => coreSubjectScore([a]) - coreSubjectScore([b]) || a.localeCompare(b))
  for (const s of order) {
    quota[s] = headTeacherQuota(bySubject.get(s)!.length, classCount, headCap, teacherCap)
    used[s] = 0
  }
  const load = new Map<number, number>()
  const assignments: Record<number, number> = {}
  let unfilledCount = 0
  for (const classId of pendingClassIds) {
    let picked: SubjectBudgetCandidate | null = null
    let pickedSubject = ''
    for (const s of order) {
      if (used[s] >= quota[s]) continue
      const pool = bySubject.get(s)!
      const idx = pool.findIndex((t) => (load.get(t.id) ?? 0) < maxLead)
      if (idx >= 0) {
        picked = pool[idx]
        pickedSubject = s
        pool.push(...pool.splice(idx, 1))
        break
      }
    }
    if (!picked) {
      unfilledCount += 1
      continue
    }
    assignments[classId] = picked.id
    used[pickedSubject] += 1
    load.set(picked.id, (load.get(picked.id) ?? 0) + 1)
  }
  const totalQuota = order.reduce((sum, s) => sum + quota[s], 0)
  return {
    assignments,
    usedBySubject: used,
    unfilledCount,
    capacityShort: totalQuota < pendingClassIds.length,
  }
}
