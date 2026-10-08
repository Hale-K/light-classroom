import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: ReactNode
  desc?: ReactNode
  /** 章节标题右侧操作区（新增/刷新等主操作） */
  extra?: ReactNode
}

/** 章节标题（Editorial Split：左大标题 + 右操作区），宽容器防窄墙排版 */
export default function PageHeader({ title, extra }: PageHeaderProps) {
  return (
    <div className="chapter">
      <div>
        <h2 className="chapter-title">{title}</h2>
      </div>
      {extra != null && <div className="chapter-actions">{extra}</div>}
    </div>
  )
}
