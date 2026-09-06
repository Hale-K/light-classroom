import { Button, Empty } from 'antd'
import dayjs from 'dayjs'
import Icon from '@/components/Icon'
import { selectDisplayName, useAuthStore } from '@/store/auth'

/**
 * 教师端 · 我的班级
 * —— 骨架版本：展示当前教师任教的班级列表，后续接真实班级 API。
 */
export default function TeacherClasses() {
  const displayName = useAuthStore(selectDisplayName)

  return (
    <div className="tc-page">
      <header className="tc-head">
        <div>
          <span className="tc-eyebrow">MY CLASSES / 我的班级</span>
          <h1>{displayName || '老师'}的班级</h1>
          <p>查看本人任教的班级、学生名单及班级公告。</p>
        </div>
        <div className="tc-term">
          <Icon name="calendar" size={16} />
          {dayjs().format('YYYY年M月D日 dddd')}
        </div>
      </header>

      <section className="tc-body">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="班级管理功能正在接入，完成后将在此展示本人任教的班级与学生信息。"
        >
          <Button type="primary" icon={<Icon name="arrow-left" size={14} />}>
            返回工作台
          </Button>
        </Empty>
      </section>
    </div>
  )
}
