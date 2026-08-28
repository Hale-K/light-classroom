import type { OrganizationUnit } from '../../types/index.ts'

export function flattenOrganizationUnits(units: OrganizationUnit[]): OrganizationUnit[] {
  return units.flatMap((unit) => [unit, ...flattenOrganizationUnits(unit.children)])
}

export function organizationExpandedKeys(units: OrganizationUnit[]): Array<'school' | number> {
  return ['school', ...flattenOrganizationUnits(units).map((unit) => unit.id)]
}
