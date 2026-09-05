type Context = Record<string, string | number | null | undefined>
const sources = new Map<string, Context>()
export function setAssistantContext(source: string, value: Context) { sources.set(source, value) }
export function clearAssistantContext(source: string) { sources.delete(source) }
export function assistantPageContext(path: string): Context {
  return path.startsWith('/scheduling') ? Object.assign({}, ...sources.values()) : {}
}
