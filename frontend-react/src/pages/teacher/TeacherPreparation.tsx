import { Button, Empty } from 'antd'
import dayjs from 'dayjs'
import Icon from '@/components/Icon'
import { selectDisplayName, useAuthStore } from '@/store/auth'

/**
 * 教师端 · 备课中心
 * —— 骨架版本：展示空白状态与本周课程概览，后续接真实备课 API。
 */
export default function TeacherPreparation() {
  const displayName = useAuthStore(selectDisplayName)

  return (
    <div className="tp-page">
      <header className="tp-head">
        <div>
          <span className="tp-eyebrow">PREPARATION / 备课中心</span>
          <h1>{displayName || '老师'}的备课</h1>
          <p>按本周课程安排，快速跳转备课与查看历史备课记录。</p>
        </div>
        <div className="tp-term">
          <Icon name="calendar" size={16} />
          {dayjs().format('YYYY年M月D日 dddd')}
        </div>
      </header>

      <section className="tp-body">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="备课中心功能正在接入，完成后将在此展示本周课程章节与备课历史。"
        >
          <Button type="primary" icon={<Icon name="arrow-left" size={14} />}>
            返回工作台
          </Button>
        </Empty>
      </section>
    </div>
  )
}
