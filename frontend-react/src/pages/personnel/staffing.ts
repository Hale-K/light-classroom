export interface TeacherCountPlanInput {
  classCount: number
  headTeacherCount: number
  maxClassesPerHeadTeacher: number
  maxClassesPerTeacher: number
}

/**
 * 计算一个学科满足班级覆盖要求所需的最少教师数。
 * 班主任先按“每人最多带 N 个班”计入，再由普通教师覆盖剩余班级。
 */
export function calculateRequiredTeacherCount({
  classCount,
  headTeacherCount,
  maxClassesPerHeadTeacher,
  maxClassesPerTeacher,
}: TeacherCountPlanInput) {
  const safeClassCount = Math.max(0, classCount)
  const safeHeadTeacherCount = Math.max(0, headTeacherCount)
  const headCapacity = Math.max(1, maxClassesPerHeadTeacher)
  const teacherCapacity = Math.max(1, maxClassesPerTeacher)
  const headCoverage = Math.min(safeClassCount, safeHeadTeacherCount * headCapacity)
  const remainingClassCount = Math.max(0, safeClassCount - headCoverage)
  const ordinaryTeacherCount = Math.ceil(remainingClassCount / teacherCapacity)

  return {
    headCapacity,
    teacherCapacity,
    headCoverage,
    remainingClassCount,
    ordinaryTeacherCount,
    requiredTeacherCount: safeHeadTeacherCount + ordinaryTeacherCount,
  }
}
