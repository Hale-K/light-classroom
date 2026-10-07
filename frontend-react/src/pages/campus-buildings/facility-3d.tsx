/**
 * 空间资源 3D 视图（three.js）：校区 → 楼宇 → 楼层 → 教室的可旋转、可点击建筑群。
 * 楼宇按校区分组排布；每层按教室数量切分成册，颜色对应用途类型；
 * 点击教室/楼宇回调给页面（联动左树），悬停显示信息浮层。
 */
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import type { Building, RoomResource } from '@/types'
import { hasRoomFeature } from './room-features'

export const ROOM_TYPE_HEX: Record<RoomResource['room_type'], number> = {
  classroom: 0x3b82f6,
  laboratory: 0x16a34a,
  computer: 0x06b6d4,
  meeting: 0xf59e0b,
  auditorium: 0x8b5cf6,
  office: 0x94a3b8,
}
const ROOM_TYPE_TEXT: Record<RoomResource['room_type'], string> = {
  classroom: '普通教室', laboratory: '实验室', computer: '计算机房',
  meeting: '会议室', auditorium: '报告厅', office: '办公室',
}

const FLOOR_HEIGHT = 1.15
const ROOM_DEPTH = 4.2
const GHOST_COLOR = 0xe2e8f0

export interface CampusGroup {
  campusId: number
  campusName: string
  buildings: Building[]
}

interface Props {
  groups: CampusGroup[]
  rooms: RoomResource[]
  highlightBuildingId?: number
  highlightFloor?: number
  highlightRoomId?: number
  onPickBuilding?: (buildingId: number) => void
  onPickRoom?: (room: RoomResource) => void
}

interface PickedInfo {
  kind: 'room' | 'building'
  room?: RoomResource
  building?: Building
}

function makeLabel(text: string, className: string) {
  const div = document.createElement('div')
  div.className = className
  div.textContent = text
  return new CSS2DObject(div)
}

function roomColor(room: RoomResource): number {
  return ROOM_TYPE_HEX[room.room_type] || 0x94a3b8
}

export default function Facility3D({
  groups, rooms, highlightBuildingId, highlightFloor, highlightRoomId,
  onPickBuilding, onPickRoom,
}: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<{
    renderer: THREE.WebGLRenderer
    labelRenderer: CSS2DRenderer
    scene: THREE.Scene
    camera: THREE.PerspectiveCamera
    controls: OrbitControls
    contentGroup: THREE.Group
    raf: number
  } | null>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const pickedRef = useRef<PickedInfo | null>(null)
  const callbacksRef = useRef({ onPickBuilding, onPickRoom })
  callbacksRef.current = { onPickBuilding, onPickRoom }

  // ---------- 引擎初始化（一次） ----------
  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0xf1f5f9)
    scene.fog = new THREE.Fog(0xf1f5f9, 60, 160)

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500)
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    const labelRenderer = new CSS2DRenderer({ element: document.createElement('div') })
    labelRenderer.domElement.style.position = 'absolute'
    labelRenderer.domElement.style.top = '0'
    labelRenderer.domElement.style.pointerEvents = 'none'
    mount.appendChild(labelRenderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.maxPolarAngle = Math.PI / 2.05
    controls.minDistance = 6
    controls.maxDistance = 120

    scene.add(new THREE.HemisphereLight(0xffffff, 0xdfe6ef, 1.05))
    const sun = new THREE.DirectionalLight(0xffffff, 1.6)
    sun.position.set(18, 30, 14)
    scene.add(sun)
    const fill = new THREE.DirectionalLight(0xffffff, 0.5)
    fill.position.set(-14, 18, -10)
    scene.add(fill)

    // 地面：浅色平面 + 网格
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(240, 160),
      new THREE.MeshStandardMaterial({ color: 0xe8edf3, roughness: 1 }),
    )
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.05
    scene.add(ground)
    const grid = new THREE.GridHelper(240, 120, 0xcbd5e1, 0xdde5ee)
    grid.position.y = 0
    scene.add(grid)

    const contentGroup = new THREE.Group()
    scene.add(contentGroup)

    engineRef.current = { renderer, labelRenderer, scene, camera, controls, contentGroup, raf: 0 }

    // 渲染循环
    let disposed = false
    const animate = () => {
      if (disposed) return
      engineRef.current?.controls.update()
      engineRef.current?.renderer.render(scene, camera)
      engineRef.current?.labelRenderer.render(scene, camera)
      engineRef.current!.raf = requestAnimationFrame(animate)
    }
    animate()

    // 尺寸自适应
    const resize = () => {
      const width = mount.clientWidth || 1
      const height = mount.clientHeight || 1
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height)
      labelRenderer.setSize(width, height)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(mount)
    resize()

    return () => {
      disposed = true
      cancelAnimationFrame(engineRef.current?.raf || 0)
      observer.disconnect()
      controls.dispose()
      contentGroup.traverse((object) => {
        const mesh = object as THREE.Mesh
        if (mesh.geometry) mesh.geometry.dispose()
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material?.dispose()
      })
      scene.clear()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
      mount.removeChild(labelRenderer.domElement)
      engineRef.current = null
    }
  }, [])

  // ---------- 内容构建（随数据/高亮变化重建） ----------
  useEffect(() => {
    const engine = engineRef.current
    if (!engine) return
    const { contentGroup, camera, controls } = engine

    // 清空旧内容
    contentGroup.traverse((object) => {
      const mesh = object as THREE.Mesh
      mesh.geometry?.dispose?.()
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material?.dispose?.()
    })
    contentGroup.clear()

    const scopeRooms = rooms.filter((room) => groups.some((group) => group.buildings.some((building) => building.id === room.building_id)))

    // 布局参数：以最大层房间数决定楼宇宽度
    let maxPerFloor = 1
    const roomsByBuilding = new Map<number, RoomResource[]>()
    for (const room of scopeRooms) {
      const list = roomsByBuilding.get(room.building_id) || []
      list.push(room)
      roomsByBuilding.set(room.building_id, list)
    }
    for (const list of roomsByBuilding.values()) {
      const byFloor = new Map<number, number>()
      list.forEach((item) => byFloor.set(item.floor, (byFloor.get(item.floor) || 0) + 1))
      maxPerFloor = Math.max(maxPerFloor, ...byFloor.values())
    }
    const buildingWidth = THREE.MathUtils.clamp(maxPerFloor * 1.35, 6, 22)
    const campusGap = 5
    const buildingGap = 2.6

    let cursorX = 0
    const totals = { minX: Infinity, maxX: -Infinity, maxTop: 0, maxZ: ROOM_DEPTH / 2 }

    for (const group of groups) {
      const groupStartX = cursorX
      for (const building of group.buildings) {
        const list = (roomsByBuilding.get(building.id) || [])
          .slice()
  .sort((a, b) => a.floor - b.floor || a.name.localeCompare(b.name, 'zh'))
        const byFloor = new Map<number, RoomResource[]>()
        list.forEach((room) => {
          const bucket = byFloor.get(room.floor) || []
          bucket.push(room)
          byFloor.set(room.floor, bucket)
        })
        const floorNumbers = new Set<number>([...byFloor.keys()])
        for (let floor = 1; floor <= building.floor_count; floor += 1) floorNumbers.add(floor)
        const topFloor = Math.max(1, ...floorNumbers)
        const isDimmed = Boolean(highlightBuildingId) && highlightBuildingId !== building.id
        const isFocused = !highlightBuildingId || highlightBuildingId === building.id
        const buildingCenterX = cursorX + buildingWidth / 2

        // 楼宇名标签（点击可下钻该楼）
        const namePickable = makeLabel(
          `${building.name}${building.code ? ` · ${building.code}` : ''}`,
          'facility3d-label-building facility3d-label-pickable',
        )
        namePickable.position.set(buildingCenterX, topFloor * FLOOR_HEIGHT + 0.55, ROOM_DEPTH / 2)
        namePickable.element.addEventListener('click', () => callbacksRef.current.onPickBuilding?.(building.id))
        namePickable.element.style.pointerEvents = 'auto'
        namePickable.element.style.cursor = 'pointer'
        contentGroup.add(namePickable)

        // 整楼线框轮廓（只描边不填充，不遮挡教室）
        const shellGeometry = new THREE.BoxGeometry(buildingWidth, topFloor * FLOOR_HEIGHT, ROOM_DEPTH)
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(shellGeometry),
          new THREE.LineBasicMaterial({ color: 0xb7c3d2, transparent: true, opacity: isDimmed ? 0.15 : 0.8 }),
        )
        edges.position.set(buildingCenterX, (topFloor * FLOOR_HEIGHT) / 2, 0)
        contentGroup.add(edges)
        shellGeometry.dispose()

        // 每层：楼板 + 教室册；无教室的规划楼层画灰显体块
        const plateGeometry = new THREE.BoxGeometry(buildingWidth + 0.08, 0.1, ROOM_DEPTH + 0.08)
        const plateMaterial = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.9, transparent: isDimmed, opacity: isDimmed ? 0.2 : 1 })
        const ghostGeometry = new THREE.BoxGeometry(buildingWidth, FLOOR_HEIGHT * 0.82, ROOM_DEPTH * 0.94)
        for (let floor = 1; floor <= topFloor; floor += 1) {
          const baseY = (floor - 1) * FLOOR_HEIGHT
          const floorRooms = byFloor.get(floor) || []

          if (!floorRooms.length) {
            // 规划楼层：灰显体块（点击选中楼宇）
            const ghost = new THREE.Mesh(ghostGeometry, new THREE.MeshStandardMaterial({
              color: GHOST_COLOR, roughness: 0.95, transparent: true,
              opacity: isDimmed ? 0.15 : 0.55,
            }))
            ghost.position.set(buildingCenterX, baseY + FLOOR_HEIGHT * 0.45, 0)
            ghost.userData = { kind: 'building', building }
            contentGroup.add(ghost)
          } else {
            // 楼板
            const plate = new THREE.Mesh(plateGeometry, plateMaterial)
            plate.position.set(buildingCenterX, baseY + 0.05, 0)
            contentGroup.add(plate)

            const floorHighlighted = highlightFloor === floor && isFocused
            const widthPerRoom = buildingWidth / floorRooms.length
            floorRooms.forEach((room, index) => {
              const isHighlight = highlightRoomId === room.id
              const material = new THREE.MeshStandardMaterial({
                color: roomColor(room),
                roughness: 0.55,
                transparent: isDimmed || (Boolean(highlightRoomId) && !isHighlight),
                opacity: isDimmed ? 0.2 : highlightRoomId && !isHighlight ? 0.32 : 1,
                emissive: isHighlight ? new THREE.Color(roomColor(room)) : new THREE.Color(0x000000),
                emissiveIntensity: isHighlight ? 0.55 : 0,
              })
              const box = new THREE.Mesh(
                new THREE.BoxGeometry(widthPerRoom * 0.86, FLOOR_HEIGHT * 0.78, ROOM_DEPTH * 0.9),
                material,
              )
              box.position.set(buildingCenterX - buildingWidth / 2 + (index + 0.5) * widthPerRoom, baseY + 0.1 + FLOOR_HEIGHT * 0.42, 0)
              box.userData = { kind: 'room', room, building }
              contentGroup.add(box)
            })

            if (floorHighlighted) {
              const ring = new THREE.Mesh(
                new THREE.BoxGeometry(buildingWidth + 0.3, FLOOR_HEIGHT + 0.1, ROOM_DEPTH + 0.3),
                new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.15 }),
              )
              ring.position.set(buildingCenterX, baseY + FLOOR_HEIGHT / 2, 0)
              contentGroup.add(ring)
            }
          }

          // 楼层标签（左缘）
          const label = makeLabel(`${floor}F`, 'facility3d-label-floor')
          label.position.set(buildingCenterX - buildingWidth / 2 - 0.7, baseY + FLOOR_HEIGHT / 2, ROOM_DEPTH / 2)
          contentGroup.add(label)
        }
        plateGeometry.dispose()
        ghostGeometry.dispose()

        cursorX += buildingWidth + buildingGap
        totals.maxX = Math.max(totals.maxX, cursorX)
        totals.maxTop = Math.max(totals.maxTop, topFloor * FLOOR_HEIGHT)
      }
      // 校区标签
      const label = makeLabel(group.campusName, 'facility3d-label-campus')
      label.position.set(groupStartX + (cursorX - buildingGap - groupStartX) / 2, totals.maxTop + 1.6, ROOM_DEPTH / 2)
      contentGroup.add(label)
      cursorX += campusGap
    }

    // 相机取景
    const spanX = Math.max(cursorX - campusGap, 8)
    const center = new THREE.Vector3(spanX / 2, totals.maxTop / 2, 0)
    controls.target.copy(center)
    const distance = Math.max(spanX * 1.15, totals.maxTop * 2.4, 14)
    camera.position.set(center.x, totals.maxTop + distance * 0.55, distance * 0.85)
    camera.lookAt(center)
    controls.update()
  }, [groups, rooms, highlightBuildingId, highlightFloor, highlightRoomId])

  // ---------- 交互：点击拾取 + 悬停浮层 ----------
  useEffect(() => {
    const engine = engineRef.current
    const mount = mountRef.current
    if (!engine || !mount) return
    const { renderer, camera } = engine
    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    let downAt: { x: number; y: number } | null = null

    const pick = (event: PointerEvent): PickedInfo | null => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const hits = raycaster.intersectObjects(engine.contentGroup.children, true)
      for (const hit of hits) {
        let object: THREE.Object3D | null = hit.object
        while (object && !object.userData?.kind) object = object.parent
        if (object?.userData?.kind) return object.userData as PickedInfo
      }
      return null
    }

    const onPointerDown = (event: PointerEvent) => { downAt = { x: event.clientX, y: event.clientY } }
    const onPointerUp = (event: PointerEvent) => {
      if (!downAt) return
      const moved = Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y)
      downAt = null
      if (moved > 5) return // 拖拽旋转不算点击
      const info = pick(event)
      if (!info) return
      if (info.kind === 'room' && info.room) callbacksRef.current.onPickRoom?.(info.room)
      else if (info.kind === 'building' && info.building) callbacksRef.current.onPickBuilding?.(info.building.id)
    }
    const onPointerMove = (event: PointerEvent) => {
      const tooltip = tooltipRef.current
      if (!tooltip) return
      const info = pick(event)
      pickedRef.current = info
      renderer.domElement.style.cursor = info ? 'pointer' : 'grab'
      if (!info) { tooltip.style.display = 'none'; return }
      const lines: string[] = []
      if (info.kind === 'room' && info.room) {
        lines.push(info.room.name + (info.room.code ? ` · ${info.room.code}` : ''))
        lines.push(`${ROOM_TYPE_TEXT[info.room.room_type]} · ${info.room.capacity} 人`)
        if (hasRoomFeature(info.room.features, 'multimedia')) lines.push('多媒体')
      } else if (info.kind === 'building' && info.building) {
        lines.push(info.building.name)
        lines.push(`${info.building.floor_count} 层 · ${info.building.room_count} 间场室`)
      }
      tooltip.innerHTML = lines.map((line, index) =>
        `<div${index === 0 ? ' class="facility3d-tip-title"' : ''}>${line}</div>`).join('')
      tooltip.style.display = 'block'
      const hostRect = mount.getBoundingClientRect()
      const left = Math.min(event.clientX - hostRect.left + 14, hostRect.width - 190)
      const top = Math.max(event.clientY - hostRect.top - 10, 8)
      tooltip.style.left = `${left}px`
      tooltip.style.top = `${top}px`
    }

    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    renderer.domElement.addEventListener('pointerup', onPointerUp)
    renderer.domElement.addEventListener('pointermove', onPointerMove)
    return () => {
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('pointerup', onPointerUp)
      renderer.domElement.removeEventListener('pointermove', onPointerMove)
    }
  }, [])

  return (
    <div className="facility3d">
      <div ref={mountRef} className="facility3d-mount" />
      <div ref={tooltipRef} className="facility3d-tip" style={{ display: 'none' }} />
      <div className="facility3d-hint">拖拽旋转 · 滚轮缩放 · 点击教室或楼宇查看详情</div>
    </div>
  )
}
