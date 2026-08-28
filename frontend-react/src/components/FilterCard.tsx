import { Card } from 'antd'
import type { CSSProperties, ReactNode } from 'react'

interface FilterCardProps {
  children: ReactNode
  style?: CSSProperties
}

/** 统一筛选卡骨架：内联查询表单容器 */
export default function FilterCard({ children, style }: FilterCardProps) {
  return (
    <Card className="app-card-hover" style={style} styles={{ body: { paddingBottom: 12 } }}>
      {children}
    </Card>
  )
}
