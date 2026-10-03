import { useMemo, type CSSProperties } from 'react'

export type TwinColumn = {
  label: string
  weekday: number
  parity: 'all' | 'odd' | 'even'
  code: string
}

export type TwinRow = { type: 'day'; period: number } | { type: 'evening'; parity: 'odd' | 'even'; period: number }

export type TwinRoomItem = {
  subject_name?: string
  teacher_name?: string
  preview?: boolean
}

type TwinRoom = {
  id: string
  label: string
  detail: string
  x: number
  y: number
  width: number
  height: number
  slotIndex: number
  item?: TwinRoomItem
  unavailable: boolean
  zone: string
}

interface DigitalTwinMapProps {
  columns: TwinColumn[]
  rows: TwinRow[]
  items: Array<TwinRoomItem | undefined>
  activeSlotIndex: number
  activeSubject?: string
  activeTeacher?: string
  robotPhase: 'pickup' | 'moving' | 'drop'
  subjectNames: string[]
  playbackActive: boolean
  isUnavailable: (column: TwinColumn, row: TwinRow) => boolean
}

const DAY_ZONE_X = [338, 508, 678, 848, 1018]
const SATURDAY_ZONE_X = [338, 508]
const EVENING_ZONE_X = [678, 933]
const STANDARD_ZONE_WIDTH = 158
const STANDARD_ZONE_CENTER = 79
const EVENING_ZONE_WIDTH = 243
const LOWER_FEEDER_X = 672

function depotAccess(index: number) {
  const column = index % 2
  const row = Math.floor(index / 2)
  const dockX = 93 + column * 132
  const dockY = 122 + row * 82
  const corridorY = dockY + 10
  return {
    dockX,
    dockY,
    corridorY,
    path: `M ${dockX} ${dockY} V ${corridorY} H 304`,
  }
}

function roomPosition(column: TwinColumn, row: TwinRow, columnIndex: number, columnCount: number) {
  if (row.type === 'day') {
    const isSaturday = column.weekday === 6
    const zoneIndex = isSaturday ? Math.max(0, columnIndex - 5) : Math.min(4, columnIndex)
    const zoneX = isSaturday ? SATURDAY_ZONE_X[zoneIndex] ?? SATURDAY_ZONE_X[0] : DAY_ZONE_X[zoneIndex] ?? DAY_ZONE_X[0]
    const zoneY = isSaturday ? 438 : 76
    const roomColumn = (row.period - 1) % 2
    const roomRow = Math.floor((row.period - 1) / 2)
    if (isSaturday) return { x: zoneX + 12 + roomColumn * 76, y: zoneY + 42 + roomRow * 42, width: 58, height: 31 }
    return { x: zoneX + 12 + roomColumn * 76, y: zoneY + 60 + roomRow * 48, width: 58, height: 34 }
  }

  const isOdd = row.parity === 'odd'
  const zoneX = isOdd ? EVENING_ZONE_X[0] : EVENING_ZONE_X[1]
  const localIndex = row.period * columnCount + columnIndex
  const roomColumn = localIndex % 5
  const roomRow = Math.floor(localIndex / 5)
  return { x: zoneX + 11 + roomColumn * 46, y: 500 + roomRow * 47, width: 38, height: 33 }
}

function zoneLabel(column: TwinColumn, row: TwinRow) {
  if (row.type === 'evening') return row.parity === 'odd' ? 'E-ODD' : 'E-EVEN'
  if (column.weekday === 6) return column.parity === 'odd' ? 'S-ODD' : 'S-EVEN'
  return `DAY-${String(column.weekday).padStart(2, '0')}`
}

function roomCode(column: TwinColumn, row: TwinRow) {
  if (row.type === 'evening') return `${row.parity === 'odd' ? 'EO' : 'EE'}-${column.weekday}-${String(row.period + 1).padStart(2, '0')}`
  if (column.weekday === 6) return `${column.parity === 'odd' ? 'SO' : 'SE'}-${String(row.period).padStart(2, '0')}`
  return `${String.fromCharCode(64 + column.weekday)}-${String(row.period).padStart(2, '0')}`
}

export default function DigitalTwinMap({
  columns,
  rows,
  items,
  activeSlotIndex,
  activeSubject,
  activeTeacher,
  robotPhase,
  subjectNames,
  playbackActive,
  isUnavailable,
}: DigitalTwinMapProps) {
  const rooms = useMemo<TwinRoom[]>(
    () =>
      rows.flatMap((row, rowIndex) =>
        columns.map((column, columnIndex) => {
          const slotIndex = rowIndex * columns.length + columnIndex
          const position = roomPosition(column, row, columnIndex, columns.length)
          return {
            id: roomCode(column, row),
            label: row.type === 'day' ? `第${row.period}节` : `${row.parity === 'odd' ? '单' : '双'}晚${row.period + 1}`,
            detail: `${column.label} · ${row.type === 'day' ? `第 ${row.period} 节` : `${row.parity === 'odd' ? '单周' : '双周'}晚自习 ${row.period + 1}`}`,
            ...position,
            slotIndex,
            item: items[slotIndex],
            unavailable: isUnavailable(column, row),
            zone: zoneLabel(column, row),
          }
        }),
      ),
    [columns, isUnavailable, items, rows],
  )

  const activeRoom = rooms.find((room) => room.slotIndex === activeSlotIndex && !room.unavailable) ?? rooms.find((room) => !room.unavailable)
  const warehouseIndex = Math.max(0, subjectNames.findIndex((name) => name === activeSubject))
  const sourceAccess = depotAccess(warehouseIndex)
  const sourceX = sourceAccess.dockX
  const sourceY = sourceAccess.dockY
  const targetX = activeRoom ? activeRoom.x + activeRoom.width / 2 : 338
  const targetY = activeRoom ? activeRoom.y + activeRoom.height / 2 : 138
  const routeHubY = activeRoom?.zone.startsWith('DAY') ? 214 : 575
  const routeSpineX = activeRoom?.zone.startsWith('DAY')
    ? (DAY_ZONE_X[Math.max(0, Number(activeRoom.zone.slice(-2)) - 1)] ?? DAY_ZONE_X[0]) + STANDARD_ZONE_CENTER
    : activeRoom?.zone === 'S-ODD'
      ? SATURDAY_ZONE_X[0] + STANDARD_ZONE_CENTER
      : activeRoom?.zone === 'S-EVEN'
        ? SATURDAY_ZONE_X[1] + STANDARD_ZONE_CENTER
        : targetX
  const routePath = `${sourceAccess.path} V ${routeHubY} H ${routeSpineX} V ${targetY} H ${targetX}`
  const routeStyle = { '--route-length': Math.max(1, Math.abs(sourceY - targetY) + Math.abs(targetX - sourceX)) } as CSSProperties

  return (
    <div className="twin-map-shell" aria-label="课程配送数字孪生沙盘">
      <div className="twin-map-toolbar">
        <div>
          <span className="twin-online-dot" />
          LIVE DIGITAL TWIN
          <b>LC-TWIN-01</b>
        </div>
        <div className="twin-map-legend">
          <span><i className="is-route" />活动轨道</span>
          <span><i className="is-room" />课位房间</span>
          <span><i className="is-target" />投递目标</span>
        </div>
      </div>
      <div className="twin-map-stage">
        <svg className="twin-map" viewBox="0 0 1200 720" role="img" aria-label="仓库、轨道和课位房间地图">
          <defs>
            <pattern id="twin-grid" width="24" height="24" patternUnits="userSpaceOnUse">
              <path d="M 24 0 L 0 0 0 24" className="twin-floor-grid" />
            </pattern>
            <filter id="twin-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="room-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="2.4" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <rect width="1200" height="720" rx="18" className="twin-floor" />
          <rect width="1200" height="720" rx="18" fill="url(#twin-grid)" />

          <g className="twin-zone-labels">
            {DAY_ZONE_X.map((x, index) => <text x={x} y="54" key={x}>{`周${['一', '二', '三', '四', '五'][index]}教学区 · DAY 0${index + 1}`}</text>)}
            <text x="338" y="416">单周周六 · ODD SAT</text>
            <text x="508" y="416">双周周六 · EVEN SAT</text>
            <text x="678" y="416">单周晚自习 · ODD EVENING</text>
            <text x={EVENING_ZONE_X[1]} y="416">双周晚自习 · EVEN EVENING</text>
          </g>

          <g className="twin-zone-blocks">
            {DAY_ZONE_X.map((x, index) => <rect x={x} y="68" width={STANDARD_ZONE_WIDTH} height="312" rx="8" key={`day-zone-${index}`} />)}
            {SATURDAY_ZONE_X.map((x, index) => <rect x={x} y="430" width={STANDARD_ZONE_WIDTH} height="252" rx="8" key={`sat-zone-${index}`} />)}
            <rect x={EVENING_ZONE_X[0]} y="430" width={EVENING_ZONE_WIDTH} height="252" rx="8" className="is-odd" />
            <rect x={EVENING_ZONE_X[1]} y="430" width={EVENING_ZONE_WIDTH} height="252" rx="8" className="is-even" />
          </g>

          <g className="twin-depot-connectors">
            {Array.from({ length: Math.ceil(subjectNames.length / 2) }, (_, row) => (
              <path d={`M 93 ${132 + row * 82} H 304`} key={`depot-corridor-${row}`} />
            ))}
            {subjectNames.map((name, index) => {
              const access = depotAccess(index)
              return <path d={`M ${access.dockX} ${access.dockY} V ${access.corridorY}`} key={`depot-track-${name}-${index}`} />
            })}
          </g>

          <g className="twin-depot-zone">
            <text x="42" y="48" className="twin-section-title">SUBJECT DEPOTS</text>
            {subjectNames.map((name, index) => {
              const depotColumn = index % 2
              const depotRow = Math.floor(index / 2)
              const x = 32 + depotColumn * 132
              const y = 66 + depotRow * 82
              const active = name === activeSubject
              return (
                <g className={`twin-depot${active ? ' is-active' : ''}`} key={`${name}-${index}`}>
                  <rect x={x} y={y} width="122" height="56" rx="7" />
                  <rect x={x + 8} y={y + 9} width="7" height="38" rx="3" className="twin-depot-signal" />
                  <text x={x + 25} y={y + 23} className="twin-depot-name">{name}仓</text>
                  <text x={x + 25} y={y + 41} className="twin-depot-code">{`D-${String(index + 1).padStart(2, '0')}`}</text>
                  <circle cx={x + 61} cy={y + 56} r="4" className="twin-dock" />
                </g>
              )
            })}
          </g>

          <g className="twin-static-network">
            <path d="M 304 64 V 665" />
            <path d="M 304 214 H 1176" />
            <path d="M 304 575 H 1176" />
            {DAY_ZONE_X.map((x) => <path d={`M ${x + STANDARD_ZONE_CENTER} 128 V 354`} key={`day-${x}`} />)}
            {SATURDAY_ZONE_X.map((x) => <path d={`M ${x + STANDARD_ZONE_CENTER} 472 V 671`} key={`sat-${x}`} />)}
            <path d={`M ${LOWER_FEEDER_X} 214 V 575`} />
          </g>
          <g className="twin-junctions">
            {[214, 575].map((y) => <circle cx="304" cy={y} r="6" key={y} />)}
            {DAY_ZONE_X.map((x) => <circle cx={x + STANDARD_ZONE_CENTER} cy="214" r="4" key={x} />)}
            <circle cx={LOWER_FEEDER_X} cy="214" r="4" />
            <circle cx={LOWER_FEEDER_X} cy="575" r="4" />
            {Array.from({ length: Math.ceil(subjectNames.length / 2) }, (_, row) => (
              <circle cx="304" cy={132 + row * 82} r="3.5" key={`depot-junction-${row}`} />
            ))}
          </g>

          <g className="twin-room-connectors">
            {rooms.filter((room) => !room.unavailable).map((room) => {
              const roomCenterX = room.x + room.width / 2
              const roomCenterY = room.y + room.height / 2
              if (room.zone.startsWith('E-')) {
                const roomEdgeY = roomCenterY < 575 ? room.y + room.height : room.y
                return <path d={`M ${roomCenterX} ${roomEdgeY} V 575`} key={`connector-${room.slotIndex}`} />
              }
              const spineX = room.zone.startsWith('DAY')
                ? (DAY_ZONE_X[Math.max(0, Number(room.zone.slice(-2)) - 1)] ?? DAY_ZONE_X[0]) + STANDARD_ZONE_CENTER
                : room.zone === 'S-ODD'
                  ? SATURDAY_ZONE_X[0] + STANDARD_ZONE_CENTER
                  : SATURDAY_ZONE_X[1] + STANDARD_ZONE_CENTER
              const roomEdgeX = roomCenterX < spineX ? room.x + room.width : room.x
              return <path d={`M ${spineX} ${roomCenterY} H ${roomEdgeX}`} key={`connector-${room.slotIndex}`} />
            })}
          </g>

          <g className="twin-rooms">
            {rooms.map((room) => {
              if (room.unavailable) return null
              const active = playbackActive && room.slotIndex === activeSlotIndex
              return (
                <g className={`twin-room${room.item ? ' is-filled' : ''}${room.unavailable ? ' is-disabled' : ''}${active ? ' is-target' : ''}`} key={`${room.id}-${room.slotIndex}`}>
                  <title>{`${room.detail}${room.item?.subject_name ? ` · ${room.item.subject_name}${room.item.teacher_name ? ` / ${room.item.teacher_name}` : ''}` : ' · 等待配送'}`}</title>
                  <rect x={room.x} y={room.y} width={room.width} height={room.height} rx="5" />
                  <text x={room.x + 5} y={room.y + 12} className="twin-room-code">{room.label}</text>
                  <text x={room.x + 5} y={room.y + 26} className="twin-room-course">
                    {room.item?.subject_name?.slice(0, 5) || '等待配送'}
                  </text>
                </g>
              )
            })}
          </g>

          {playbackActive && activeRoom && activeSubject && (
            <g className={`twin-active-route is-${robotPhase}`} style={routeStyle}>
              <path d={routePath} className="twin-route-reserved" pathLength="1" />
              <path d={routePath} className="twin-route-live" pathLength="1" />
              <circle cx={targetX} cy={targetY} r="13" className="twin-target-ring" />
              {robotPhase === 'pickup' && (
                <g className="twin-agv is-loading" transform={`translate(${sourceX} ${sourceY})`}>
                  <circle r="13" className="twin-agv-halo" />
                  <circle r="8" className="twin-agv-body" />
                  <text y="3" textAnchor="middle">1</text>
                </g>
              )}
              {robotPhase === 'moving' && (
                <g className="twin-agv is-moving" key={`${activeSlotIndex}-${activeSubject}-moving`}>
                  <circle r="13" className="twin-agv-halo" />
                  <circle r="8" className="twin-agv-body" />
                  <text y="3" textAnchor="middle">1</text>
                  <animateMotion dur="5.35s" path={routePath} fill="freeze" calcMode="linear" />
                </g>
              )}
              {robotPhase === 'drop' && (
                <g className="twin-agv is-dropping" transform={`translate(${targetX} ${targetY})`}>
                  <circle r="13" className="twin-agv-halo" />
                  <circle r="8" className="twin-agv-body" />
                  <text y="3" textAnchor="middle">1</text>
                </g>
              )}
            </g>
          )}
        </svg>

        <div className="twin-map-hud twin-map-hud-left">
          <span>AGV PIPELINE NETWORK</span>
          <strong>{playbackActive ? 'SIMULATING' : 'STANDBY'}</strong>
          <small>仓库接驳 {subjectNames.length} · 课位支路 {rooms.filter((room) => !room.unavailable).length} · 全线连通</small>
        </div>
        {activeRoom && activeSubject && playbackActive && (
          <div className="twin-map-hud twin-map-hud-job">
            <span>{robotPhase === 'pickup' ? 'PICKUP' : robotPhase === 'moving' ? 'IN TRANSIT' : 'DELIVERING'}</span>
            <strong>{activeSubject} → {activeRoom.id}</strong>
            <small>{activeTeacher || '自动匹配教师'} · {activeRoom.detail}</small>
          </div>
        )}
      </div>
    </div>
  )
}
