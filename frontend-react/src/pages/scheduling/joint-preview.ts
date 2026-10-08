export type PreviewView = 'student' | 'admin' | 'walk'
export type TeacherWorkloadLesson = { teacher_id: number; teacher_name: string; subject_name: string; kind: 'admin' | 'walk' }
export type TeacherWorkload = {
  teacher_id: number; teacher_name: string; subject_name: string; admin: number; walk: number; total: number; subject_total: number; difference: number
}

export function summarizeTeacherWorkload(lessons: TeacherWorkloadLesson[], subjectName?: string): TeacherWorkload[] {
  const loads = new Map<string, Omit<TeacherWorkload, 'total' | 'difference'>>()
  for (const lesson of lessons.filter(row => !subjectName || row.subject_name === subjectName)) {
    const key = `${lesson.teacher_id}:${lesson.subject_name}`
    const row = loads.get(key) ?? {
      teacher_id: lesson.teacher_id, teacher_name: lesson.teacher_name, subject_name: lesson.subject_name, admin: 0, walk: 0, subject_total: 0,
    }
    row[lesson.kind] += 1
    loads.set(key, row)
  }
  const values = [...loads.values()].map(row => ({ ...row, total: row.admin + row.walk, subject_total: 0, difference: 0 }))
  const subjectTotals = new Map<string, { total: number; count: number }>()
  for (const row of values) {
    const group = subjectTotals.get(row.subject_name) ?? { total: 0, count: 0 }
    group.total += row.total
    group.count += 1
    subjectTotals.set(row.subject_name, group)
  }
  return values.map(row => {
    const group = subjectTotals.get(row.subject_name)!
    return { ...row, subject_total: group.total, difference: row.total - group.total / group.count }
  }).sort((a, b) => b.subject_total - a.subject_total || a.subject_name.localeCompare(b.subject_name, 'zh-CN')
    || b.total - a.total || a.teacher_name.localeCompare(b.teacher_name, 'zh-CN'))
}

export function filterPreviewStudents<T extends { name: string; class_id: number }>(
  students: T[], classId?: number, query = '',
): T[] {
  const name = query.trim().toLocaleLowerCase()
  return students.filter(s => (classId === undefined || s.class_id === classId)
    && s.name.toLocaleLowerCase().includes(name))
}
export function primaryClassLabel(students: { class_id: number; primary_subject_name?: string }[], classId: number): string {
  const names = [...new Set(students.filter(s => s.class_id === classId).map(s => s.primary_subject_name).filter(Boolean))]
    .sort((a, b) => (a === '物理' ? -1 : b === '物理' ? 1 : (a ?? '').localeCompare(b ?? '', 'zh')))
  if (!names.length) return '首选科目未提供'
  return names.length === 1 ? `${names[0]}班` : `${names.join('／')}混合班`
}
export function selectPreviewLessons<T extends { kind: string; class_id: number }>(
  lessons: T[], view: PreviewView, id: number | undefined,
  students: { id: number; class_id: number; teaching_class_ids: number[] }[],
): T[] {
  if (view !== 'student') return lessons.filter(r => r.kind === view && r.class_id === id)
  const student = students.find(s => s.id === id)
  if (!student) return []
  return lessons.filter(r => r.kind === 'admin' ? r.class_id === student.class_id
    : r.kind === 'walk' && student.teaching_class_ids.includes(r.class_id))
}
