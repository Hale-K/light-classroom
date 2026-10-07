import type { SchedulingGridSlot } from '../../types/index.ts'

export interface SlotPoint { day: number; period: number }
export interface SelectableSlot extends SlotPoint { kind: 'daytime' | 'evening' }
export type SlotMode = 'all' | 'odd' | 'even' | 'disabled'
export const slotKey = ({ day, period }: SlotPoint) => `${day}:${period}`

export function selectSlotRectangle(cells: SelectableSlot[], start: SlotPoint, end: SlotPoint) {
  return cells.filter(cell => cell.day >= Math.min(start.day, end.day) && cell.day <= Math.max(start.day, end.day)
    && cell.period >= Math.min(start.period, end.period) && cell.period <= Math.max(start.period, end.period))
}

export function applySlotSelection(previous: SchedulingGridSlot[], selected: SelectableSlot[], mode: SlotMode): SchedulingGridSlot[] {
  const keys = new Set(selected.map(slotKey))
  const overrides = previous.filter(slot => !keys.has(slotKey({ day: slot.weekday, period: slot.period })))
  for (const cell of selected) for (const leg of ['odd', 'even'] as const) {
    overrides.push({ weekday: cell.day, period: cell.period, week_parity: leg,
      slot_type: mode === 'all' || mode === leg ? cell.kind : 'disabled' })
  }
  return overrides
}
