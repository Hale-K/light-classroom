import { Button, Empty } from 'antd'
import dayjs from 'dayjs'
import Icon from '@/components/Icon'
import { selectDisplayName, useAuthStore } from '@/store/auth'

/**
 * 教师端 · 我的学生
 * —— 骨架版本：展示本人任教班级的学生名单，后续接真实学生 API。
 * 与教导主任"学生档案"不同：教师视角只看自己班级的学生，不需要导入/导出/分班管理。
 */
export default function TeacherStudents() {
  const displayName = useAuthStore(selectDisplayName)

  return (
    <div className="ts-page">
      <header className="ts-head">
        <div>
          <span className="ts-eyebrow">MY STUDENTS / 我的学生</span>
          <h1>{displayName || '老师'}的学生</h1>
          <p>查看本人任教班级的学生名单与学情概况。</p>
        </div>
        <div className="ts-term">
          <Icon name="calendar" size={16} />
          {dayjs().format('YYYY年M月D日 dddd')}
        </div>
      </header>

      <section className="ts-body">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="学生名单功能正在接入，完成后将在此展示本人任教班级的学生列表。"
        >
          <Button type="primary" icon={<Icon name="arrow-left" size={14} />}>
            返回工作台
          </Button>
        </Empty>
      </section>
    </div>
  )
}
