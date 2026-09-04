import { useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Icon from '@/components/Icon'
import { routeTitle } from '@/router/meta'
import { useAuthStore } from '@/store/auth'
import './assistant-dock.css'

const DOCK_KEY = 'zh_assistant_dock_collapsed'

type Panel = 'support' | 'notice' | 'docs' | 'home' | null
type HelpTab = 'faq' | 'guide' | 'start'

function Face({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="32" fill="#d8e4f4" />
      <circle cx="32" cy="24" r="11" fill="#3a322c" />
      <path d="M18 58c2-14 8-22 14-22s12 8 14 22" fill="#1c1a1a" />
      <path d="M22 58c1-10 6-16 10-16s9 6 10 16" fill="#c9d9ec" />
      <ellipse cx="32" cy="28" rx="9" ry="10" fill="#f3c7b0" />
      <circle cx="28.5" cy="27.5" r="1.1" fill="#2a2420" />
      <circle cx="35.5" cy="27.5" r="1.1" fill="#2a2420" />
      <path d="M29 32.5c1.2 1.4 4.8 1.4 6 0" fill="none" stroke="#c48a78" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  )
}

const FAQ = [
  { hot: true, q: '排课和手工调课有什么区别？', a: '排课按规则生成整张课表；调课只改已有格子，不会重跑求解器。' },
  { hot: true, q: '生成课表要等多久？', a: '任务在后台跑。白班大约两分半，晚班大约一分半，浏览器里不用干等超时。' },
  { hot: false, q: '教师档案完成度为什么对不上课时？', a: '完成度按网格可排课时核算，单双周按 0.5 计，上限 100%。停用教师不进列表。' },
  { hot: true, q: '多所学校数据会串吗？', a: '不会。请求头 X-School-Code 隔离租户，登录后只看见本校数据。' },
  { hot: false, q: '怎么导入学生名单？', a: '在学生档案里导入。含名单和密码哈希的 SQL 不要提交到仓库。' },
  { hot: false, q: '系统设置改了学年为什么课表空了？', a: '网格和学年学期决定容量。改完要重新生成，旧课表不会自动迁移。' },
]

const GUIDES = [
  { q: '从课时到生成课表', a: '先填课时与任教，再开规则组，最后点生成。冲突格会标红。' },
  { q: '给教师排多班课', a: '规则里教师多选用斜杠拼接的姓名；「多班教师」与单班互斥。' },
  { q: '调课碰到冲突', a: '目标格被占用会提示碰撞，换空格或先把原课挪开。' },
]

const STARTS = [
  { q: '第一次登录看哪', a: '工作台看进度，系统设置核对学年学期，再进排课。' },
  { q: '开发环境怎么起', a: '后端 8001、前端 5176，另开 Celery 消费 scheduling 队列。' },
  { q: '生产必须跑迁移', a: 'APP_ENV 不是 dev 时请 alembic upgrade head，不要靠启动建表。' },
]

function pageTasks(pathname: string): { label: string; path: string }[] {
  const extras = [
    { label: '帮我打开排课工作台，核对规则后再生成', path: '/scheduling' },
    { label: '帮我看教师档案完成度是否按课时算满', path: '/teacher-profiles' },
    { label: '帮我去系统设置核对学年学期和网格', path: '/settings' },
  ]
  if (pathname.startsWith('/scheduling')) {
    return [{ label: '当前就在排课：先看课时与规则组，冲突格会标红', path: '/scheduling' }, extras[1], extras[2]]
  }
  return extras
}

export default function AssistantDock() {
  const location = useLocation()
  const navigate = useNavigate()
  const schoolCode = useAuthStore((s) => s.schoolCode)
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(DOCK_KEY) === '1')
  const [panel, setPanel] = useState<Panel>(null)
  const [noticeUnread, setNoticeUnread] = useState(true)
  const [draft, setDraft] = useState('')
  const [thread, setThread] = useState<{ role: 'user' | 'bot'; text: string }[]>([])
  const [helpTab, setHelpTab] = useState<HelpTab>('faq')
  const [helpQuery, setHelpQuery] = useState('')
  const [faqOffset, setFaqOffset] = useState(0)
  const [openFaq, setOpenFaq] = useState<string | null>(null)
  const [tipOn, setTipOn] = useState(true)

  const tasks = useMemo(() => pageTasks(location.pathname), [location.pathname])
  const pageName = routeTitle(location.pathname)

  const setDockCollapsed = (next: boolean) => {
    setCollapsed(next)
    localStorage.setItem(DOCK_KEY, next ? '1' : '0')
  }

  const toggle = (next: Panel) => {
    setPanel((cur) => (cur === next ? null : next))
    if (next === 'notice') setNoticeUnread(false)
  }

  const replyFor = (text: string) => {
    const t = text.trim()
    if (/排课/.test(t)) return '排课建议：先对齐课时与规则组，再点生成。生成走后台任务，浏览器里不用干等超时。'
    if (/教师|档案/.test(t)) return '教师档案完成度按网格课时核算，停用教师不会出现在列表里。'
    if (/设置|学年/.test(t)) return '学年学期和网格结构会改排课容量，改完再生成课表。'
    return `我还没有接大模型。当前页面是「${pageName}」，可以点上面的任务卡片先跳过去。`
  }

  const send = (text?: string) => {
    const content = (text ?? draft).trim()
    if (!content) return
    setDraft('')
    setThread((prev) => [...prev, { role: 'user', text: content }, { role: 'bot', text: replyFor(content) }])
    setPanel('home')
  }

  const runTask = (item: { label: string; path: string }) => {
    send(item.label)
    navigate(item.path)
  }

  const helpItems = helpTab === 'faq' ? FAQ : helpTab === 'guide' ? GUIDES : STARTS
  const rotated = helpTab === 'faq' ? [...FAQ.slice(faqOffset), ...FAQ.slice(0, faqOffset)] : helpItems
  const filtered = rotated.filter((item) => !helpQuery.trim() || item.q.includes(helpQuery.trim()) || item.a.includes(helpQuery.trim()))

  return (
    <>
      <aside className={`assist-dock${collapsed ? ' is-collapsed' : ''}`} aria-label="轻课堂助手">
        {!collapsed && (
          <>
            <div className="assist-dock-capsule">
              <div className="assist-dock-slot">
                <button
                  type="button"
                  className={`assist-dock-icon${panel === 'support' ? ' is-on' : ''}`}
                  title="咨询"
                  onClick={() => toggle('support')}
                >
                  <Icon name="headset" size={20} />
                </button>
                {panel === 'support' && (
                  <div className="assist-menu" role="menu">
                    <button type="button" onClick={() => { setPanel('home'); setThread([{ role: 'bot', text: '使用上卡住了可以说页面和操作。排课、账号、导入都可以问。' }]) }}>
                      <strong>使用咨询</strong>
                      <span>排课、账号、导入怎么配，按当前学校说明</span>
                    </button>
                    <button type="button" onClick={() => { setPanel('home'); setThread([{ role: 'bot', text: '生成失败或导入报错，把提示原文发过来。后台任务请看 Celery 日志。' }]) }}>
                      <strong>故障协助</strong>
                      <span>生成超时、冲突标红、名单导入失败</span>
                    </button>
                    <button type="button" onClick={() => { setPanel('home'); setDraft('建议：') }}>
                      <strong>产品建议</strong>
                      <span>哪一步别扭，写下来就是改进方向</span>
                    </button>
                  </div>
                )}
              </div>
              <button
                type="button"
                className={`assist-dock-icon${panel === 'notice' ? ' is-on' : ''}`}
                title="通知"
                onClick={() => toggle('notice')}
              >
                <span className="assist-dock-cloud">
                  <Icon name="cloud" size={18} />
                  <Icon name="bell" size={10} className="assist-dock-bell" />
                  {noticeUnread && <i className="assist-dock-badge" />}
                </span>
              </button>
              <button
                type="button"
                className={`assist-dock-icon${panel === 'docs' ? ' is-on' : ''}`}
                title="帮助"
                onClick={() => toggle('docs')}
              >
                <Icon name="book" size={20} />
              </button>
              <button
                type="button"
                className={`assist-dock-icon${panel === 'home' ? ' is-on' : ''}`}
                title="提问"
                onClick={() => toggle('home')}
              >
                <Icon name="mood" size={20} />
              </button>
            </div>
            <button type="button" className="assist-dock-avatar" title="轻课堂助手" onClick={() => toggle('home')}>
              <Face />
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

      {panel === 'docs' && (
        <section className="assist-help" aria-label="帮助文档">
          <header className="assist-help-head">
            <strong>{pageName}</strong>
            <button type="button" title="关闭" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <div className="assist-help-search">
            <Icon name="search" size={16} />
            <input value={helpQuery} placeholder="搜索" onChange={(e) => setHelpQuery(e.target.value)} />
            {helpQuery ? (
              <button type="button" className="assist-help-clear" onClick={() => setHelpQuery('')} aria-label="清空">
                <Icon name="x" size={14} />
              </button>
            ) : null}
          </div>
          <div className="assist-help-tags">
            {['排课生成', '教师档案', '导入学生'].map((tag) => (
              <button key={tag} type="button" onClick={() => setHelpQuery(tag.slice(0, 2))}>
                {tag}
              </button>
            ))}
          </div>
          <div className="assist-help-tools">
            <span>热门文档</span>
            <button type="button" onClick={() => { setHelpTab('faq'); setFaqOffset((n) => (n + 1) % FAQ.length) }}>
              <Icon name="rotate" size={14} />
              换一换
            </button>
          </div>
          <div className="assist-help-tabs">
            {([['faq', '热门问题'], ['guide', '操作指南'], ['start', '快速入门']] as const).map(([id, label]) => (
              <button key={id} type="button" className={helpTab === id ? 'is-on' : ''} onClick={() => { setHelpTab(id); setOpenFaq(null) }}>
                {label}
              </button>
            ))}
          </div>
          <ul className="assist-help-list">
            {filtered.map((item) => (
              <li key={item.q}>
                <button type="button" onClick={() => setOpenFaq(openFaq === item.q ? null : item.q)}>
                  <Icon name="file-text" size={16} />
                  <span>
                    {item.q}
                    {'hot' in item && item.hot ? <i className="assist-hot" /> : null}
                  </span>
                </button>
                {openFaq === item.q && <p>{item.a}</p>}
              </li>
            ))}
          </ul>
          {tipOn && (
            <div className="assist-help-tip">
              <button type="button" className="assist-help-tip-x" onClick={() => setTipOn(false)}>
                <Icon name="x" size={12} />
              </button>
              <strong>3 步跑通排课</strong>
              <span>课时 → 规则组 → 生成。冲突格会标红。</span>
            </div>
          )}
        </section>
      )}

      {panel === 'notice' && (
        <section className="assist-help assist-help-slim" aria-label="通知">
          <header className="assist-help-head">
            <strong>通知</strong>
            <button type="button" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <p className="assist-sheet-cap">暂无新的系统公告。排课任务完成后会在这里提示。</p>
        </section>
      )}

      {panel === 'home' && (
        <section className="assist-sheet" aria-label="轻课堂助手对话">
          <header className="assist-sheet-bar">
            <button type="button" title="新对话" onClick={() => setThread([])}>
              <Icon name="plus" size={16} />
            </button>
            <button type="button" title="关闭" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <div className="assist-sheet-body">
            {thread.length === 0 && (
              <>
                <Face className="assist-sheet-face" />
                <h2 className="assist-sheet-hi">Hi，我是轻课堂助手</h2>
                <p className="assist-sheet-hi">欢迎随时提问</p>
                <p className="assist-sheet-cap">当前在「{pageName}」。任务点一下，我帮你跳到对应页。</p>
                <div className="assist-task-list">
                  {tasks.map((item) => (
                    <button key={item.path + item.label} type="button" className="assist-task" onClick={() => runTask(item)}>
                      <Icon name="sparkles" size={16} />
                      <span>{item.label}</span>
                      <Icon name="chevron-right" size={16} />
                    </button>
                  ))}
                </div>
              </>
            )}
            {thread.length > 0 && (
              <div className="assist-thread">
                {thread.map((msg, i) => (
                  <div key={i} className={`assist-bubble is-${msg.role}`}>{msg.text}</div>
                ))}
              </div>
            )}
          </div>
          <div className="assist-composer">
            <textarea
              rows={3}
              value={draft}
              placeholder="排课、档案、设置，有问题都可以问"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <div className="assist-composer-bar">
              <span>当前页 · {pageName}</span>
              <button type="button" className="assist-send" disabled={!draft.trim()} onClick={() => send()} aria-label="发送">
                <Icon name="send" size={16} />
              </button>
            </div>
          </div>
          <footer className="assist-sheet-foot">
            <span>回答由规则提示生成，仅供参考</span>
            <span>{schoolCode || '—'}</span>
          </footer>
        </section>
      )}
    </>
  )
}
