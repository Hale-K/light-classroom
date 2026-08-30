/** 班主任批量分配算法：候选按序轮派，不设置固定带班数量上限。 */
export interface HeadTeacherCandidate { id: number }
export interface HeadTeacherAllocationResult {
  assignments: Record<number, number>
  unfilledCount: number
}

export function allocateHeadTeachers(
  pendingClassIds: number[],
  candidates: HeadTeacherCandidate[],
  existing: Record<number, number>,
): HeadTeacherAllocationResult {
  const assignments = { ...existing }
  const pool = [...candidates]
  let unfilledCount = 0
  for (const classId of pendingClassIds) {
    const candidate = pool[0]
    if (!candidate) {
      unfilledCount += 1
      continue
    }
    assignments[classId] = candidate.id
    pool.push(...pool.splice(0, 1))
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
