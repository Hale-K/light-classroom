export function groupRoster<T extends { student_name: string; class_name: string | null }>(
  items: T[], query = '',
) {
  const keyword = query.trim().toLocaleLowerCase()
  const groups = new Map<string, { name: string; total: number; members: T[] }>()
  for (const item of items) {
    const name = item.class_name || '未分班'
    const group = groups.get(name) ?? { name, total: 0, members: [] }
    group.total += 1
    if (!keyword || item.student_name.toLocaleLowerCase().includes(keyword)) group.members.push(item)
    groups.set(name, group)
  }
  return [...groups.values()].filter(group => group.members.length > 0)
    .sort((a, b) => a.name.localeCompare(b.name, 'zh', { numeric: true }))
}
