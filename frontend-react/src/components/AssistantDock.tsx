import { App, Drawer, Input } from 'antd'
import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Icon from '@/components/Icon'
import { routeTitle } from '@/router/meta'
import './assistant-dock.css'

const DOCK_KEY = 'zh_assistant_dock_collapsed'

type Panel = 'assist' | 'notice' | 'docs' | 'feedback' | null

function pageHint(pathname: string): string {
  if (pathname.startsWith('/scheduling')) {
    return '当前在排课。可先核对课时与规则组，再生成课表；冲突格会标红。'
  }
  if (pathname.startsWith('/teacher-profiles')) {
    return '当前在教师档案。完成度按网格课时核算，停用教师不会出现在列表里。'
  }
  if (pathname.startsWith('/students') || pathname.startsWith('/classes')) {
    return '当前在班级学生。导入前请确认学校代码与学年学期一致。'
  }
  if (pathname.startsWith('/settings')) {
    return '当前在系统设置。学年学期、网格结构会直接影响排课容量。'
  }
  return `当前页面是「${routeTitle(pathname)}」。点下面快捷入口可跳到常用模块。`
}

export default function AssistantDock() {
  const { message } = App.useApp()
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(DOCK_KEY) === '1')
  const [panel, setPanel] = useState<Panel>(null)
  const [noticeUnread, setNoticeUnread] = useState(true)
  const [feedback, setFeedback] = useState('')

  const hint = useMemo(() => pageHint(location.pathname), [location.pathname])

  const setDockCollapsed = (next: boolean) => {
    setCollapsed(next)
    localStorage.setItem(DOCK_KEY, next ? '1' : '0')
  }

  const open = (next: Panel) => {
    setPanel(next)
    if (next === 'notice') setNoticeUnread(false)
  }

  const submitFeedback = () => {
    const text = feedback.trim()
    if (!text) {
      message.warning('请先写下遇到的问题')
      return
    }
    setFeedback('')
    setPanel(null)
    message.success('已记下，后续会接到工单通道')
  }

  return (
    <>
      <aside className={`assist-dock${collapsed ? ' is-collapsed' : ''}`} aria-label="轻课堂助手">
        {!collapsed && (
          <>
            <div className="assist-dock-capsule">
              <button type="button" className="assist-dock-icon" title="助手" onClick={() => open('assist')}>
                <Icon name="headset" size={20} />
              </button>
              <button type="button" className="assist-dock-icon" title="通知" onClick={() => open('notice')}>
                <span className="assist-dock-cloud">
                  <Icon name="cloud" size={18} />
                  <Icon name="bell" size={10} className="assist-dock-bell" />
                  {noticeUnread && <i className="assist-dock-badge" />}
                </span>
              </button>
              <button type="button" className="assist-dock-icon" title="帮助" onClick={() => open('docs')}>
                <Icon name="book" size={20} />
              </button>
              <button type="button" className="assist-dock-icon" title="反馈" onClick={() => open('feedback')}>
                <Icon name="mood" size={20} />
              </button>
            </div>
            <button type="button" className="assist-dock-avatar" title="轻课堂助手" onClick={() => open('assist')}>
              <svg viewBox="0 0 64 64" aria-hidden="true">
                <circle cx="32" cy="32" r="32" fill="#d8e4f4" />
                <circle cx="32" cy="24" r="11" fill="#3a322c" />
                <path d="M18 58c2-14 8-22 14-22s12 8 14 22" fill="#1c1a1a" />
                <path d="M22 58c1-10 6-16 10-16s9 6 10 16" fill="#c9d9ec" />
                <ellipse cx="32" cy="28" rx="9" ry="10" fill="#f3c7b0" />
                <circle cx="28.5" cy="27.5" r="1.1" fill="#2a2420" />
                <circle cx="35.5" cy="27.5" r="1.1" fill="#2a2420" />
                <path d="M29 32.5c1.2 1.4 4.8 1.4 6 0" fill="none" stroke="#c48a78" strokeWidth="1.1" strokeLinecap="round" />
              </svg>
            </button>
          </>
        )}
        <button
          type="button"
          className="assist-dock-toggle"
          aria-label={collapsed ? '展开助手栏' : '收起助手栏'}
          onClick={() => setDockCollapsed(!collapsed)}
        >
          <Icon name={collapsed ? 'chevron-left' : 'chevron-right'} size={16} />
        </button>
      </aside>

      <Drawer
        title={
          panel === 'notice'
            ? '通知'
            : panel === 'docs'
              ? '帮助'
              : panel === 'feedback'
                ? '意见反馈'
                : '轻课堂助手'
        }
        open={panel != null}
        onClose={() => setPanel(null)}
        width={380}
        className="assist-drawer"
        destroyOnClose
      >
        {panel === 'assist' && (
          <div className="assist-panel">
            <p className="assist-panel-lead">{hint}</p>
            <div className="assist-quick">
              <button type="button" onClick={() => { setPanel(null); navigate('/scheduling') }}>
                排课工作台
              </button>
              <button type="button" onClick={() => { setPanel(null); navigate('/teacher-profiles') }}>
                教师档案
              </button>
              <button type="button" onClick={() => { setPanel(null); navigate('/settings') }}>
                系统设置
              </button>
            </div>
          </div>
        )}
        {panel === 'notice' && (
          <div className="assist-panel">
            <p className="assist-notice">暂无新的系统公告。排课任务完成后会在这里提示。</p>
          </div>
        )}
        {panel === 'docs' && (
          <div className="assist-panel">
            <ul className="assist-docs">
              <li>多租户靠请求头 X-School-Code 隔离</li>
              <li>排课生成走 Celery，不要在浏览器里干等超时</li>
              <li>生产库变更请用 alembic upgrade head</li>
            </ul>
          </div>
        )}
        {panel === 'feedback' && (
          <div className="assist-panel">
            <Input.TextArea
              rows={5}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="卡在哪一步、期望怎样，写在这里"
            />
            <button type="button" className="assist-submit" onClick={submitFeedback}>
              发送
            </button>
          </div>
        )}
      </Drawer>
    </>
  )
}
