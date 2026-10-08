export type AssistantMode = 'standard' | 'plan'

export function modeForTurn(turns: { role: string; assistantMode?: AssistantMode }[], fallback: AssistantMode): AssistantMode {
  return [...turns].reverse().find(item => item.role === 'user')?.assistantMode ?? fallback
}

export function canUsePageActions(mode: AssistantMode): boolean {
  return mode === 'standard'
}
