import type { ScheduleEntry } from '@/types'

export type StudentWalkLesson = Omit<ScheduleEntry, 'class_id'> & {
  teaching_class_id: number
  teaching_class_name: string
}

export function combineStudentSchedule(
  admin: ScheduleEntry[], walk: StudentWalkLesson[],
  scope: { academic_year: string; term: string; class_id?: number | null },
): ScheduleEntry[] {
  const inTerm = (entry: { academic_year: string; term: string }) =>
    entry.academic_year === scope.academic_year && entry.term === scope.term
  return [
    ...admin.filter(entry => inTerm(entry) && entry.class_id === scope.class_id),
    ...walk.filter(inTerm).map(entry => ({
      ...entry, id: -entry.id, class_id: -entry.teaching_class_id,
      class_name: `走班 · ${entry.teaching_class_name}`, week_parity: entry.week_parity || 'all' as const,
    })),
  ].sort((a, b) => a.weekday - b.weekday || a.period - b.period)
}
