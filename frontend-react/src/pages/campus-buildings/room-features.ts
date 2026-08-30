export type RoomFeatures = string[] | Record<string, unknown> | null | undefined

export function hasRoomFeature(features: RoomFeatures, feature: string): boolean {
  if (Array.isArray(features)) return features.includes(feature)
  if (!features || typeof features !== 'object') return false

  const record = features as Record<string, unknown>
  return record[feature] === true || Object.values(record).includes(feature)
}
