/** Convert structured API failures to user-facing text, never raw JSON. */
export function normalizeErrorDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail.trim() || undefined
  if (Array.isArray(detail)) {
    const parts = detail.map(d => {
      const item = (d ?? {}) as { loc?: unknown; msg?: unknown }
      const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
      const msg = typeof item.msg === 'string' ? item.msg : ''
      return [loc, msg].filter(Boolean).join(': ')
    }).filter(Boolean)
    if (!parts.length) return undefined
    return `参数校验失败：${parts[0]}${parts.length > 1 ? `（等 ${parts.length} 条校验错误）` : ''}`
  }
  if (!detail || typeof detail !== 'object') return undefined
  const value = detail as { message?: unknown; diagnostics?: unknown; rule_failures?: unknown }
  const headline = typeof value.message === 'string' ? value.message : ''
  const messages = [value.diagnostics, value.rule_failures].flatMap(items =>
    Array.isArray(items) ? items.flatMap(item => {
      const text = item && typeof item === 'object' ? item.message : undefined
      return typeof text === 'string' && text && !headline.includes(text) ? [text] : []
    }) : [])
  const unique = [...new Set(messages)]
  const result = [headline, ...unique.slice(0, 3)].filter(Boolean).join('；')
  return result ? result + (unique.length > 3 ? `（另有${unique.length - 3}项，请检查课时和资源配置）` : '') : undefined
}
