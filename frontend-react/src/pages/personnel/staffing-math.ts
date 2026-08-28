/** 师资测算公式(纯函数,供师资调整建议与测试使用)。

口径:
- 按工作量:某学科总课时 ÷ 教师每周课时上限,向上取整
- 按带班:班主任数 + ⌈(班级数 − 班主任×班主任容量) ÷ 普通教师容量⌉
  容量 = min(带班数上限, ⌊每周课时上限 ÷ 每班课时⌋),至少为 1
- 建议人数 = max(按工作量, 按带班)
- 缺少 = max(0, 建议 − 全校可用);调整 = 建议 − 当前
*/

export interface SubjectStaffInput {
  subject: string
  /** 每班每周课时 */
  weeklyPeriods: number
  /** 目标年级班级数 */
  classCount: number
  /** 该学科已被设为班主任的人数 */
  headTeachers: number
  /** 已任职到目标年级部的该学科人数 */
  current: number
  /** 全校可用(来源学科组在职、未被其他年级部锁定) */
  available: number
  /** 班主任最多带班数 */
  maxClassesPerHeadTeacher: number
  /** 非班主任最多带班数 */
  maxClassesPerTeacher: number
  /** 教师每周课时上限 */
  maxWeeklyPeriods: number
}

export interface SubjectStaffResult {
  subject: string
  weeklyPeriods: number
  totalPeriods: number
  headCapacity: number
  teacherCapacity: number
  byWorkload: number
  byClasses: number
  recommended: number
  adjustment: number
  shortage: number
}

export function computeSubjectStaff(input: SubjectStaffInput): SubjectStaffResult {
  const {
    subject, weeklyPeriods, classCount, headTeachers, current, available,
    maxClassesPerHeadTeacher, maxClassesPerTeacher, maxWeeklyPeriods,
  } = input
  const totalPeriods = classCount * weeklyPeriods
  const byWorkload = Math.ceil(totalPeriods / maxWeeklyPeriods)
  const headCapacity = Math.max(1, Math.min(maxClassesPerHeadTeacher, Math.floor(maxWeeklyPeriods / weeklyPeriods)))
  const teacherCapacity = Math.max(1, Math.min(maxClassesPerTeacher, Math.floor(maxWeeklyPeriods / weeklyPeriods)))
  const byClasses = headTeachers + Math.ceil(
    Math.max(0, classCount - headTeachers * headCapacity) / teacherCapacity,
  )
  const recommended = Math.max(byWorkload, byClasses)
  return {
    subject,
    weeklyPeriods,
    totalPeriods,
    headCapacity,
    teacherCapacity,
    byWorkload,
    byClasses,
    recommended,
    adjustment: recommended - current,
    shortage: Math.max(0, recommended - available),
  }
}
