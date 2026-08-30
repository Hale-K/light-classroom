import type { StaffAppointment } from '@/types'

type SubjectAppointment = Pick<StaffAppointment, 'id' | 'organization_unit_id' | 'staff_id' | 'position_code' | 'status'>

export function diffTeacherSubjectAppointments(
  appointments: SubjectAppointment[],
  teacherId: number,
  subjectUnitIds: number[],
  selectedSubjectUnitIds: number[],
) {
  const subjectUnitIdSet = new Set(subjectUnitIds)
  const selectedSubjectUnitIdSet = new Set(selectedSubjectUnitIds)
  const current = appointments.filter((item) => (
    item.staff_id === teacherId &&
    item.status === 'active' &&
    item.position_code === 'member' &&
    subjectUnitIdSet.has(item.organization_unit_id)
  ))
  const currentSubjectUnitIds = new Set(current.map((item) => item.organization_unit_id))

  return {
    toCreate: selectedSubjectUnitIds.filter((id) => !currentSubjectUnitIds.has(id)),
    toRemove: current.filter((item) => !selectedSubjectUnitIdSet.has(item.organization_unit_id)).map((item) => item.id),
  }
}
