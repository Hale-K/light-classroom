import { Button, Empty } from 'antd'
import { useNavigate } from 'react-router-dom'

interface SelectEmptyGuideProps {
  description: string
  path: string
  actionLabel?: string
  compact?: boolean
}

/** Select 下拉数据为空时的下一步入口，避免用户只能看到默认的 No data。 */
export default function SelectEmptyGuide({
  description,
  path,
  actionLabel = '去管理页创建',
  compact = false,
}: SelectEmptyGuideProps) {
  const navigate = useNavigate()
  return (
    <div className="zh-select-empty-guide">
      {compact ? <div className="zh-select-empty-guide-title">{description}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />}
      <Button type="link" onMouseDown={(event) => event.preventDefault()} onClick={() => navigate(path)}>
        {actionLabel}
      </Button>
    </div>
  )
}
