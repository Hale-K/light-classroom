import type { Key } from 'react'
import { Tree } from 'antd'
import type { DataNode } from 'antd/es/tree'
import Icon from '@/components/Icon'
import type { OrganizationTreeResult, OrganizationUnit, StaffAppointment } from '@/types'

export type PersonnelTreeKey = 'school' | 'unassigned' | number

function unitNodes(units: OrganizationUnit[], counts: Map<number, number>): DataNode[] {
  return units.map((unit) => ({
    key: unit.id,
    title: <span className="zh-org-tree-title"><span>{unit.name}</span><small>{counts.get(unit.id) || 0}</small></span>,
    children: unitNodes(unit.children, counts),
  }))
}

export default function PersonnelTree({ data, appointments, totalCount, unassignedCount, selectedKey, expandedKeys, onExpand, onSelect }: {
  data?: OrganizationTreeResult
  appointments: StaffAppointment[]
  totalCount: number
  unassignedCount: number
  selectedKey: PersonnelTreeKey
  expandedKeys: Key[]
  onExpand: (keys: Key[]) => void
  onSelect: (key: PersonnelTreeKey) => void
}) {
  const counts = new Map<number, number>()
  appointments.forEach((item) => counts.set(item.organization_unit_id, (counts.get(item.organization_unit_id) || 0) + 1))
  const treeData: DataNode[] = [{
    key: 'school',
    title: <span className="zh-org-tree-title zh-org-school-title"><span>{data?.school.name || '当前学校'}</span><small>{totalCount}</small></span>,
    children: [
      ...unitNodes(data?.units || [], counts),
      { key: 'unassigned', title: <span className="zh-org-tree-title personnel-unassigned"><span>未分配组织</span><small>{unassignedCount}</small></span> },
    ],
  }]

  return <aside className="personnel-tree-panel" aria-label="人员组织目录">
    <div className="zh-organization-panel-title"><Icon name="sitemap" size={16} /><strong>组织与人员</strong></div>
    <Tree blockNode treeData={treeData} expandedKeys={expandedKeys} onExpand={onExpand}
      selectedKeys={[selectedKey]} onSelect={(keys) => onSelect((keys[0] ?? 'school') as PersonnelTreeKey)} />
  </aside>
}
