export function filterWalkAssignments<T extends { subject_id: number; teacher_id?: number | null }>(
  items: T[], subjectId?: number, teacherId?: number,
): T[] {
  return items.filter(item => (subjectId === undefined || item.subject_id === subjectId)
    && (teacherId === undefined || item.teacher_id === teacherId))
}
