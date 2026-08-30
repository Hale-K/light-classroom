/** 师资测算公式：只按总课时和教师每周课时上限估算人数。 */

export interface SubjectStaffInput {
  subject: string
  /** 每班每周课时 */
  weeklyPeriods: number
  /** 目标年级班级数 */
  classCount: number
  /** 已任职到目标年级部的该学科人数 */
  current: number
  /** 全校可用(来源学科组在职、未被其他年级部锁定) */
  available: number
  /** 教师每周课时上限 */
  maxWeeklyPeriods: number
}

export interface SubjectStaffResult {
  subject: string
  weeklyPeriods: number
  totalPeriods: number
  byWorkload: number
  recommended: number
  adjustment: number
  shortage: number
}

export function computeSubjectStaff(input: SubjectStaffInput): SubjectStaffResult {
  const {
    subject, weeklyPeriods, classCount, current, available, maxWeeklyPeriods,
  } = input
  const totalPeriods = classCount * weeklyPeriods
  const byWorkload = Math.ceil(totalPeriods / maxWeeklyPeriods)
  const recommended = byWorkload
  return {
    subject,
    weeklyPeriods,
    totalPeriods,
    byWorkload,
    recommended,
    adjustment: recommended - current,
    shortage: Math.max(0, recommended - available),
  }
}
