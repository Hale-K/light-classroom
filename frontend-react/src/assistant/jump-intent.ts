import type { JumpLink } from '@/assistant/run'
import { placeLabel } from '@/assistant/place'

export type JumpReplyDecision =
  | { kind: 'confirm'; jump: JumpLink }
  | { kind: 'cancel' }
  | { kind: 'none' }

const NEGATIVE = /^(不|不用|不要|不了|先不|暂时不|取消|留在这里|不用跳|别跳)(用|要|了|跳转|过去|打开)?$/
const POSITIVE = /^(好|好的|好啊|可以|可以的|行|行的|是|是的|嗯|嗯嗯|确定|确认|没问题)(吧|啊|呀)?$|^(好|好的|可以|可以的|行|是的|那就)?(请|麻烦)?(帮我)?(去|跳转|过去|打开|前往|进入|切换|带我去)(吧|啊|呀|页面|页签)?$/

function normalized(text: string): string {
  return text.trim().replace(/[，。！？!?、\s]/g, '')
}

export function decideJumpReply(text: string, jumps: JumpLink[]): JumpReplyDecision {
  if (!jumps.length) return { kind: 'none' }
  const value = normalized(text)
  if (NEGATIVE.test(value)) return { kind: 'cancel' }

  const named = jumps.find((jump) => {
    const place = placeLabel(jump.path).replace(/[「」·\s]/g, '')
    const label = jump.label.replace(/[「」·\s]/g, '')
    return (value.includes(place) || value.includes(label)) && /去|跳|打开|前往|进入|切换/.test(value)
  })
  if (named) return { kind: 'confirm', jump: named }
  if (jumps.length === 1 && POSITIVE.test(value)) return { kind: 'confirm', jump: jumps[0] }
  return { kind: 'none' }
}
