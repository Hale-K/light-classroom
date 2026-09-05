export function newMsgId(): string {
  return `m${Date.now().toString(36).slice(-5)}${Math.random().toString(36).slice(2, 6)}`
}

export function assistLog(id: string, step: string, detail?: unknown) {
  if (detail === undefined) {
    console.info(`[assist ${id}] ${step}`)
    return
  }
  console.info(`[assist ${id}] ${step}`, detail)
}
