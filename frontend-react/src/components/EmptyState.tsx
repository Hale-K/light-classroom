import { Button } from 'antd'
import Icon from './Icon'

interface EmptyStateProps {
  icon?: string
  title?: string
  desc?: string
  /** 保持与数据填充态一致的占位高度 */
  height?: number | string
  actionText?: string
  onAction?: () => void
}

/** 空状态占位：高度可配（默认撑满容器），图标用柔和 pastel 底 */
export default function EmptyState({
  icon = 'file-text',
  title = '暂无数据',
  desc,
  height,
  actionText,
  onAction,
}: EmptyStateProps) {
  return (
    <div
      className="empty-state"
      style={{ height: typeof height === 'number' ? `${height}px` : height }}
    >
      <div className="empty-icon">
        <Icon name={icon} size={38} />
      </div>
      <div className="empty-title">{title}</div>
      {desc && <div className="empty-desc">{desc}</div>}
      {actionText && (
        <Button type="primary" ghost className="empty-btn" onClick={onAction}>
          {actionText}
        </Button>
      )}
    </div>
  )
}
