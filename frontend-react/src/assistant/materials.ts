export type AssistantMaterial = {
  id: string
  name: string
  text: string
  truncated: boolean
  original_chars?: number | null
  /** 结构化分析摘要（Excel 列统计 / PDF 页数 / Word 结构），后端解析时生成 */
  analysis?: string
}

export const MATERIAL_ACCEPT = '.txt,.md,.markdown,.csv,.json,.pdf,.docx,.xlsx'

export function mergeMaterials(current: AssistantMaterial[], added: AssistantMaterial[]): AssistantMaterial[] {
  const items = [...new Map([...current, ...added].map(item => [item.id, item])).values()]
  if (items.length > 8) throw new Error('每条消息最多添加 8 个附件')
  if (items.reduce((total, item) => total + item.text.length, 0) > 24000) {
    throw new Error('附件内容合计超过 24000 字，请减少附件')
  }
  return items
}

export function materialsForTurn(turns: { role: string; materials?: AssistantMaterial[] }[]): AssistantMaterial[] {
  return [...turns].reverse().find(item => item.role === 'user' && item.materials !== undefined)?.materials ?? []
}
