import { useState } from 'react'
import { Alert, Button, Empty, Input, Modal, Skeleton } from 'antd'
import type { gaokaoApi } from '@/api'
import { groupRoster } from './roster-groups'
import './walk-roster.css'

type RosterItem = Awaited<ReturnType<typeof gaokaoApi.teachingClassRoster>>['items'][number]

export default function WalkRosterModal({ name, items, loading, error, onClose }: {
  name: string
  items: RosterItem[]
  loading: boolean
  error: string
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const groups = groupRoster(items, query)
  const classCount = groupRoster(items).length
  const matched = groups.reduce((sum, group) => sum + group.members.length, 0)
  const searching = Boolean(query.trim())

  return <Modal open centered title="教学班学生名单" onCancel={onClose} width={760}
    className="walk-roster-modal" footer={<Button onClick={onClose}>关闭</Button>}>
    <p className="walk-roster-class-name">{name}</p>
    {loading ? <div className="walk-roster-loading" role="status" aria-label="正在加载学生名单">
      <Skeleton active paragraph={{ rows: 5 }} />
    </div> : error ? <Alert type="error" showIcon message={error} /> : <>
      <div className="walk-roster-summary">
        <div><span>教学班人数</span><strong>{items.length}<small>人</small></strong></div>
        <div><span>来源行政班</span><strong>{classCount}<small>个班</small></strong></div>
      </div>
      <div className="walk-roster-toolbar">
        <Input aria-label="搜索学生姓名" placeholder="搜索学生姓名" allowClear
          value={query} onChange={event => setQuery(event.target.value)} />
        <span role="status" aria-live="polite">{searching ? `找到 ${matched} 人` : '按行政班分组'}</span>
      </div>
      <div className="walk-roster-list">
        {groups.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={searching ? '未找到匹配的学生，请换个姓名试试' : '该教学班暂无学生'} />}
        {groups.map(group => <section key={group.name} className="walk-roster-group" aria-label={`${group.name}学生名单`}>
          <div className="walk-roster-group-head">
            <h3>{group.name}</h3>
            <span>{searching ? `匹配 ${group.members.length} / ${group.total} 人` : `${group.total} 人`}</span>
          </div>
          <ul className="walk-roster-students">
            {group.members.map(student => <li key={student.student_id}>{student.student_name}</li>)}
          </ul>
        </section>)}
      </div>
    </>}
  </Modal>
}
