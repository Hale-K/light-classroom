/** seating 领域 API（由 api/index.ts 拆分）。 */
import type {
  SeatArrangement,
  SeatEntry,
} from '@/types'
import { http, unwrap } from './http'

export const seatingApi = {
  list: (class_id: number) =>
    unwrap<SeatArrangement[]>(http.get('/seating/arrangements', { params: { class_id } })),
  generate: (data: {
    class_id: number
    rows: number
    cols: number
    order: string
    layout: string
    pairing?: string
    seed?: number
    exam_id?: number
    front_student_ids?: number[]
    separation_pairs?: number[][]
    adjacency_pairs?: number[][]
    effective_from?: string
    effective_to?: string
  }) => unwrap<SeatArrangement>(http.post('/seating/generate', data)),
  activate: (id: number) =>
    unwrap<SeatArrangement>(http.patch(`/seating/arrangements/${id}/activate`)),
  updateSeats: (id: number, seats: SeatEntry[]) =>
    unwrap<SeatArrangement>(http.patch(`/seating/arrangements/${id}/seats`, { seats })),
}

