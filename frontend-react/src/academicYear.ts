const now = new Date()
const currentStartYear = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1

export const CURRENT_ACADEMIC_YEAR = `${currentStartYear}-${currentStartYear + 1}`

export function academicYearOptions(values: Array<string | null | undefined> = []) {
  const years = new Set<string>([CURRENT_ACADEMIC_YEAR])
  values.forEach((value) => {
    if (value && /^\d{4}-\d{4}$/.test(value)) years.add(value)
  })
  return Array.from(years)
    .sort((left, right) => right.localeCompare(left))
    .map((value) => ({ label: `${value}学年`, value }))
}
