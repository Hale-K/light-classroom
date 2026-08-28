import { Card } from 'antd'
import type { ReactNode } from 'react'

interface TableCardProps {
  children: ReactNode
  title?: ReactNode
  extra?: ReactNode
}

/** 统一表格卡骨架：与筛选卡拉开章节间距，表格留呼吸边距 */
export default function TableCard({ children, title, extra }: TableCardProps) {
  return (
    <Card
      className="section-gap"
      title={title}
      extra={extra}
      styles={{
        body: { padding: 16 },
        header: title ? { borderBottom: '1px solid var(--border)' } : undefined,
      }}
    >
      {children}
    </Card>
  )
}
