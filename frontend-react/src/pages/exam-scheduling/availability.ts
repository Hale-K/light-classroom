export function unavailableAt(values: string[], date: string, start: string, end: string, session: number) {
  const weekday = new Date(`${date}T12:00:00Z`).getUTCDay() || 7
  return values.some(value => {
    if (value === `${date}#${session}`) return true
    const [, day, from, to] = value.split('#')
    return value.startsWith('weekly#') && Number(day) === weekday && start < to && from < end
  })
}
