/** facility 领域 API（由 api/index.ts 拆分）。 */
import type {
  Campus,
  Building,
  FacilityOverview,
  RoomResource,
  ResourceAllocationRule,
  AllocationPreviewResult,
} from '@/types'
import { http, unwrap } from './http'

export const facilityApi = {
  overview: () => unwrap<FacilityOverview>(http.get('/facilities/overview')),
  createCampus: (data: { name: string; address?: string; student_capacity?: number }) =>
    unwrap<Campus>(http.post('/facilities/campuses', data)),
  createBuilding: (data: { campus_id: number; name: string; code?: string; floor_count: number }) =>
    unwrap<Building>(http.post('/facilities/buildings', data)),
  updateBuildingStatus: (id: number, status: 'active' | 'maintenance' | 'disabled') =>
    unwrap<Building>(http.patch(`/facilities/buildings/${id}/status`, { status })),
  rooms: (params?: { building_id?: number; room_type?: RoomResource['room_type']; keyword?: string; academic_year?: string; term?: '1' | '2' }) =>
    unwrap<RoomResource[]>(http.get('/facilities/rooms', { params })),
  createRoom: (data: {
    building_id: number
    name: string
    code?: string
    floor: number
    capacity: number
    room_type: RoomResource['room_type']
    features: string[]
    is_schedulable: boolean
    is_exam_enabled: boolean
  }) => unwrap<RoomResource>(http.post('/facilities/rooms', data)),
  createRoomsBatch: (data: {
    building_id: number
    floor: number
    count: number
    start_number: number
    name_prefix: string
    capacity: number
    multimedia: boolean
    is_schedulable: boolean
  }) => unwrap<{ created_count: number; skipped_count: number; skipped_names: string[] }>(http.post('/facilities/rooms/batch', data)),
  allocationRules: (params?: { academic_year?: string; term?: '1' | '2' }) => unwrap<ResourceAllocationRule[]>(http.get('/facilities/allocation-rules', { params })),
  previewAllocationRule: (data: Record<string, unknown>) =>
    unwrap<AllocationPreviewResult>(http.post('/facilities/allocation-rules/preview', data)),
  createAllocationRule: (data: Record<string, unknown>) =>
    unwrap<ResourceAllocationRule>(http.post('/facilities/allocation-rules', data)),
  deleteAllocationRule: (id: number) => unwrap<{ deleted_class_count: number; released_student_count: number; deleted_teacher_binding_count: number; released_room_count: number }>(http.delete(`/facilities/allocation-rules/${id}`)),
  releaseAllocationRule: (id: number) => unwrap<{ released_room_count: number; unbound_class_count: number; released_teacher_binding_count: number; rule_id: number }>(http.post(`/facilities/allocation-rules/${id}/release`)),
  classPlanningPreview: (data: {
    grade_id: number
    grade_group_id?: number
    academic_year?: string
    term?: '1' | '2'
    elite_count: number
    key_count: number
    experimental_count: number
    regular_count: number
    strategy: 'random' | 'snake' | 'custom'
    custom_room_ids?: number[]
    custom_sub_strategy?: 'random' | 'snake'
    building_preferences?: Array<{ building_id: number; preferred_types: string[] }>
    skip_generated?: boolean
    inspect_only?: boolean
  }) => unwrap<{
    grade_id: number
    grade_group_id: number | null
    cohort_label: string | null
    grade_name: string
    grade_label: string
    existing_count: number
    available_room_count: number
    requested_total: number
    item_count: number
    items: Array<{
      room_id: number
      room_name: string
      building_id: number
      building_name: string
      floor: number
      code: string | null
      capacity: number
      sequence_no: number
      class_type: string
      proposed_class_name: string
    }>
    remaining_pools: { elite: number; key: number; experimental: number; regular: number }
    student_count: number
    assigned_student_count: number
    remaining_student_count: number
    available_capacity: number
    capacity_sufficient: boolean
    capacity_gap: number
    recommended_class_count: number
  }>(http.post('/facilities/class-planning/preview', data)),
  classPlanningExecute: (data: {
    grade_id: number
    grade_group_id?: number
    academic_year?: string
    term?: '1' | '2'
    elite_count: number
    key_count: number
    experimental_count: number
    regular_count: number
    strategy: 'random' | 'snake' | 'custom'
    custom_room_ids?: number[]
    custom_sub_strategy?: 'random' | 'snake'
    building_preferences?: Array<{ building_id: number; preferred_types: string[] }>
    skip_generated?: boolean
    inspect_only?: boolean
    plan?: Array<{
      room_id: number
      room_name: string
      building_id: number
      building_name: string
      floor: number
      code: string | null
      capacity: number
      sequence_no: number
      class_type: string
      proposed_class_name: string
    }>
  }) => unwrap<{
    created_count: number
    by_type: Record<string, number>
    class_ids: number[]
  }>(http.post('/facilities/class-planning/execute', data)),
}

