import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/http'
import { assistantApi, type AssistantPlan, type AssistantRun } from '@/api'
import { watchAssistantRun } from '@/assistant/task'
import { assistantPageContext } from '@/assistant/context'
import { useAuthStore } from '@/store/auth'
import AssistantRulePlan from '@/components/AssistantRulePlan'
import Icon from '@/components/Icon'
import { type HoursDraft } from '@/assistant/hoursPlan'
import { routeTeacherMessage, type Extra } from '@/assistant/orchestrate'
import { runAssistantTool, type JumpLink } from '@/assistant/run'
import { assistLog, newMsgId } from '@/assistant/trace'
import { hereOf, jumpLabel, placeLabel, samePlace } from '@/assistant/place'
import { pageSnapshot, type AssistantTask } from '@/assistant/skills'
import './assistant-dock.css'

const DOCK_KEY = 'zh_assistant_dock_collapsed'
const STAR_HINT = ['很不满意', '不满意', '一般', '满意', '非常满意']
const RATE_KEY = 'zh_assistant_satisfaction'

type ChatMsg = {
  role: 'user' | 'bot'
  text: string
  mid?: string
  hoursDraft?: HoursDraft
  plan?: AssistantPlan
  awaitRules?: boolean
  jumps?: JumpLink[]
  advice?: string
  choices?: { label: string; send: string }[]
  think?: { done: string[]; live?: string }
}

type Panel = 'support' | 'notice' | 'docs' | 'home' | 'rate' | null
type HelpTab = 'faq' | 'guide' | 'start'

function Face({ className }: { className?: string }) {
  return (
    <img
      className={className}
      src="/assistant-icon.png"
      alt=""
      width={64}
      height={64}
      draggable={false}
    />
  )
}

function ThinkDial({ live, progress, connection }: { live: string; progress: AssistantRun | null; connection: string }) {
  const heartbeatRecent = progress && Date.now() - Date.parse(progress.heartbeat_at) < 12000
  return (
    <div className="assist-dial is-live">
      <span className="assist-dial-kicker">处理进度</span>
      <div className="assist-dial-window" aria-live="polite">
        <div key={live} className="assist-dial-face">
          {live}
        </div>
      </div>
      {progress && <div className="assist-progress-detail">
        <span>已等待 {progress.elapsed_seconds} 秒 · 当前阶段 {progress.phase_elapsed_seconds} 秒</span>
        <span>{connection || (heartbeatRecent ? '后台仍在响应' : '暂未收到新的后台心跳，正在核对状态')}</span>
        {progress.phase_elapsed_seconds >= 15 && <span>当前阶段暂未返回新结果。你可以继续使用其他页面，或停止本轮处理。</span>}
        <details><summary>查看执行记录</summary><ol>{progress.events.map((event, i) => <li key={i}>{event.message}</li>)}</ol></details>
      </div>}
      {!progress && connection && <div role="status">{connection}</div>}
    </div>
  )
}

function MidCopy({ id }: { id: string }) {
  const [ok, setOk] = useState(false)
  return (
    <span className="assist-mid">
      <code>{id}</code>
      <button
        type="button"
        className="assist-mid-copy"
        aria-label={ok ? '已复制' : '复制消息编号'}
        title={ok ? '已复制' : '复制消息编号'}
        onClick={() => {
          void navigator.clipboard.writeText(id).then(() => {
            setOk(true)
            window.setTimeout(() => setOk(false), 1200)
          })
        }}
      >
        <Icon name="clipboard" size={12} />
        {ok ? '已复制' : '复制'}
      </button>
    </span>
  )
}

const FAQ = [
  { hot: true, q: '排课和手工调课有什么区别？', a: '排课按规则生成整张课表；调课只改已有格子，不会重跑求解器。' },
  { hot: true, q: '生成课表要等多久？', a: '生成任务在后台运行，耗时取决于课量和规则。请查看生成面板的实际阶段；长时间没有更新时可以让助手核对任务状态。' },
  { hot: false, q: '教师档案完成度为什么对不上课时？', a: '完成度按网格可排课时核算，单双周按 0.5 计，上限 100%。停用教师不进列表。' },
  { hot: true, q: '多所学校数据会串吗？', a: '不会。登录后只看见本校数据。' },
  { hot: false, q: '怎么导入学生名单？', a: '在学生档案里导入。' },
  { hot: false, q: '系统设置改了学年为什么课表空了？', a: '网格和学年学期决定容量。改完要重新生成，旧课表不会自动迁移。' },
]

const GUIDES = [
  { q: '从课时到生成课表', a: '系统设置核对学年学期 → 课时管理填节数 → 任教关系对老师 → 课位结构确认网格 → 规则组 → 你自己点生成。' },
  { q: '禁排和连堂去哪', a: '说「禁排」或「物理要连堂」，会打开规则组。' },
  { q: '备课和对课怎么配', a: '说「备课时间」或「物理历史对课」，会按现成模板说明先硬后软。' },
  { q: '给教师排多班课', a: '规则里教师多选用斜杠拼接的姓名；「多班教师」与单班互斥。' },
  { q: '调课碰到冲突', a: '目标格被占用会提示碰撞，换空格或先把原课挪开。助手不会改格子。' },
]

const STARTS = [
  { q: '第一次登录看哪', a: '先到系统设置核对学年学期和网格，再进排课填课时和任教。' },
  { q: '想排高一怎么说', a: '直接说「我想排高一的课」，会打开该年级课时管理。' },
  { q: '每周36节怎么安排', a: '直接说「每周36个课时怎么安排」，会对照网格拆科目预览。' },
  { q: '什么时候可以点生成', a: '课时、任教、课位、规则都过完后，在排课页点「生成课表」。' },
]

function StarPick({
  value,
  onChange,
}: {
  value: number
  onChange: (n: number) => void
}) {
  const [hover, setHover] = useState(0)
  const shown = hover || value
  return (
    <div className="assist-stars" role="radiogroup" aria-label="选择星级">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          className={`assist-star${shown >= n ? ' is-on' : ''}`}
          aria-label={`${n} 星`}
          aria-checked={value === n}
          role="radio"
          onMouseEnter={() => setHover(n)}
          onMouseLeave={() => setHover(0)}
          onFocus={() => setHover(n)}
          onBlur={() => setHover(0)}
          onClick={() => onChange(n)}
        >
          <Icon name="star" size={18} />
        </button>
      ))}
    </div>
  )
}

export default function AssistantDock() {
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(DOCK_KEY) === '1')
  const [panel, setPanel] = useState<Panel>(null)
  const [noticeUnread, setNoticeUnread] = useState(true)
  const [draft, setDraft] = useState('')
  const [thread, setThread] = useState<ChatMsg[]>([])
  const [chatting, setChatting] = useState(false)
  const [helpTab, setHelpTab] = useState<HelpTab>('faq')
  const [helpQuery, setHelpQuery] = useState('')
  const [faqOffset, setFaqOffset] = useState(0)
  const [openFaq, setOpenFaq] = useState<string | null>(null)
  const [tipOn, setTipOn] = useState(true)
  const [satisfaction, setSatisfaction] = useState(() => {
    const raw = Number(localStorage.getItem(RATE_KEY) || 0)
    return raw >= 1 && raw <= 5 ? raw : 0
  })
  const threadRef = useRef<ChatMsg[]>([])
  const busyRef = useRef(false)
  const dirtyRef = useRef(false)
  const lockMergeRef = useRef(false)
  const forcedRef = useRef<{ tool: AssistantTask['tool']; path?: string; extra?: Extra & { hoursDraft?: HoursDraft } } | null>(null)
  const midRef = useRef('')
  const agentConversationRef = useRef(false)
  const activeRunRef = useRef<string | null>(null)
  const epochRef = useRef(0)
  const [runProgress, setRunProgress] = useState<AssistantRun | null>(null)
  const [connectionNote, setConnectionNote] = useState('')
  const [recoverable, setRecoverable] = useState(false)
  const schoolCode = useAuthStore((s) => s.schoolCode)
  const userId = useAuthStore((s) => s.user?.id)
  const runStorageKey = `lc-assistant-run:${schoolCode}:${userId ?? 'anonymous'}`

  const commitThread = (updater: (prev: ChatMsg[]) => ChatMsg[]) => {
    const next = updater(threadRef.current)
    threadRef.current = next
    setThread(next)
  }

  const confirmJumps = (result: { path?: string; jumps?: JumpLink[] }, hereNow: string): JumpLink[] => {
    const raw =
      result.jumps && result.jumps.length
        ? result.jumps
        : result.path
          ? [{ label: jumpLabel(result.path), path: result.path }]
          : []
    return raw.filter((item) => !item.label.startsWith('已在') && !samePlace(hereNow, item.path))
  }

  const here = hereOf(location.pathname, location.search)
  const snap = useMemo(() => pageSnapshot(location.pathname), [location.pathname])
  const pageName = placeLabel(here)
  const tasks = snap.tasks
  const loopingRef = useRef(false)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const abortedRef = useRef(false)

  const stopTurn = () => {
    if (activeRunRef.current) {
      setConnectionNote('正在请求取消，等待后台确认…')
      void assistantApi.cancelRun(activeRunRef.current).catch(() => {
        setConnectionNote('取消请求暂未确认，仍在核对任务状态。')
      })
      return
    }
    abortedRef.current = true
    abortRef.current?.abort()
  }

  useEffect(() => {
    const el = composerRef.current
    if (!el) return
    if (!draft) {
      el.style.height = '22px'
      el.style.overflowY = 'hidden'
      return
    }
    el.style.height = '22px'
    const cap = 110
    const next = Math.min(Math.max(el.scrollHeight, 22), cap)
    el.style.height = `${next}px`
    el.style.overflowY = el.scrollHeight > cap ? 'auto' : 'hidden'
  }, [draft, panel])

  const setDockCollapsed = (next: boolean) => {
    setCollapsed(next)
    localStorage.setItem(DOCK_KEY, next ? '1' : '0')
  }

  const toggle = (next: Panel) => {
    setPanel((cur) => (cur === next ? null : next))
    if (next === 'notice') setNoticeUnread(false)
  }

  const collectOpenTurn = (msgs: ChatMsg[]) => {
    const users: string[] = []
    for (let i = msgs.length - 1; i >= 0; i -= 1) {
      const item = msgs[i]
      if (item.role === 'user') users.unshift(item.text)
      else if (item.role === 'bot' && item.text && !item.text.startsWith('已到「')) break
    }
    return users.join('\n\n')
  }

  const replaceThinkBot = (msgs: ChatMsg[], bot: ChatMsg) => {
    const next = [...msgs]
    let idx = next.length - 1
    for (let i = next.length - 1; i >= 0; i -= 1) {
      if (next[i].role === 'bot' && !next[i].text) {
        idx = i
        break
      }
    }
    next[idx] = bot
    return next
  }

  const upsertThink = (msgs: ChatMsg[], live: string) => {
    const next = [...msgs]
    let idx = -1
    for (let i = next.length - 1; i >= 0; i -= 1) {
      if (next[i].role === 'bot' && !next[i].text) {
        idx = i
        break
      }
    }
    if (idx < 0) {
      next.push({ role: 'bot', text: '', mid: midRef.current || undefined, think: { done: [], live } })
      return next
    }
    const cur = next[idx]
    if (cur.think?.live === live) return next
    const done = (cur.think?.live ? [...(cur.think.done || []), cur.think.live] : [...(cur.think?.done || [])]).slice(-12)
    next[idx] = { ...cur, mid: cur.mid || midRef.current || undefined, think: { done, live } }
    return next
  }

  const runLoop = async (resumeId?: string) => {
    if (loopingRef.current) return
    loopingRef.current = true
    busyRef.current = true
    abortedRef.current = false
    abortRef.current = new AbortController()
    setChatting(true)
    setPanel('home')
    const epoch = epochRef.current
    setRecoverable(false)
    setConnectionNote('')
    setRunProgress(null)
    let failed = false
    const halt = () => {
      if (abortedRef.current || epoch !== epochRef.current) throw new DOMException('已停止', 'AbortError')
    }
    try {
      for (;;) {
        halt()
        dirtyRef.current = false
        lockMergeRef.current = false
        commitThread((prev) => upsertThink(prev, '分析意图'))
        const merged = resumeId ? '恢复上一轮助手任务' : collectOpenTurn(threadRef.current)
        if (!merged) break
        const tid = midRef.current || newMsgId()
        midRef.current = tid
        assistLog(tid, 'turn', merged.slice(0, 80))
        const hereNow = hereOf(location.pathname, location.search)
        const withTrace = (extra?: Extra & { hoursDraft?: HoursDraft }) => ({ ...extra, here: hereNow, traceId: tid })
        const forced = forcedRef.current
        forcedRef.current = null
        if (forced) {
          lockMergeRef.current = forced.tool === 'executeHours'
          assistLog(tid, 'forced', forced.tool)
          const result = await runAssistantTool(forced.tool, forced.path, withTrace(forced.extra), (line) => {
            if (epoch === epochRef.current) commitThread((prev) => upsertThink(prev, line))
          })
          halt()
          if (dirtyRef.current) continue
          const jumps = confirmJumps(result, hereNow)
          commitThread((prev) => {
            const thinkBot = [...prev].reverse().find((m) => m.role === 'bot' && !m.text)
            const done = thinkBot?.think?.live
              ? [...(thinkBot.think.done || []), thinkBot.think.live]
              : thinkBot?.think?.done || []
            return replaceThinkBot(prev, {
              role: 'bot',
              text: result.report,
              mid: tid,
              hoursDraft: result.hoursDraft,
              awaitRules: result.awaitRules,
              jumps,
              advice: result.advice,
              think: done.length ? { done } : undefined,
            })
          })
          break
        }
        const route = resumeId || agentConversationRef.current ? { kind: 'llm' as const } : routeTeacherMessage(merged, hereNow)
        assistLog(tid, 'route', route.kind === 'tool' ? `${route.tool} ${route.path}` : route.kind)
        halt()
        if (dirtyRef.current) continue
        if (route.kind === 'say') {
          commitThread((prev) => {
            const next = upsertThink(prev, '按口径直接回复')
            const thinkBot = [...next].reverse().find((m) => m.role === 'bot' && !m.text)
            const done = thinkBot?.think?.live
              ? [...(thinkBot.think.done || []), thinkBot.think.live]
              : thinkBot?.think?.done || []
            return replaceThinkBot(next, { role: 'bot', text: route.text, mid: tid, think: { done } })
          })
          if (dirtyRef.current) continue
          break
        }
        if (route.kind === 'tool') {
          lockMergeRef.current = route.tool === 'executeHours'
          const result = await runAssistantTool(route.tool, route.path || undefined, withTrace(route.extra), (line) => {
            if (epoch === epochRef.current) commitThread((prev) => upsertThink(prev, line))
          })
          halt()
          if (dirtyRef.current) continue
          const jumps = confirmJumps(result, hereNow)
          commitThread((prev) => {
            const thinkBot = [...prev].reverse().find((m) => m.role === 'bot' && !m.text)
            const done = thinkBot?.think?.live
              ? [...(thinkBot.think.done || []), thinkBot.think.live]
              : thinkBot?.think?.done || []
            return replaceThinkBot(prev, {
              role: 'bot',
              text: result.report,
              mid: tid,
              hoursDraft: result.hoursDraft,
              awaitRules: result.awaitRules,
              jumps,
              advice: result.advice,
              think: done.length ? { done } : undefined,
            })
          })
          break
        }
        commitThread((prev) => upsertThink(prev, resumeId ? '正在恢复上次任务状态' : '已收到，正在提交任务'))
        agentConversationRef.current = true
        const history = threadRef.current.filter((m) => m.text)
        halt()
        // HTTP 部署（非安全上下文）下浏览器不提供 crypto.randomUUID，走 getRandomValues 回退
        const runId = resumeId || (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID().replaceAll('-', '')
          : Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join(''))
        activeRunRef.current = runId
        sessionStorage.setItem(runStorageKey, runId)
        if (!resumeId) await assistantApi.startRun({
            request_id: runId,
            messages: history.slice(-20).map((m) => ({
              role: m.role === 'bot' ? 'assistant' : 'user',
              content: m.plan ? `${m.text}\n草稿状态：${m.plan.status}\n${m.plan.summary}` : m.text,
            })),
            page_title: pageName,
            page_path: hereNow,
            page_context: assistantPageContext(hereNow),
            can: snap.can,
            cannot: snap.cannot,
            message_id: tid,
          }, abortRef.current?.signal)
        if (dirtyRef.current) void assistantApi.cancelRun(runId).catch(() => undefined)
        resumeId = undefined
        halt()
        const outcome = await watchAssistantRun(runId, abortRef.current!.signal, (run) => {
          if (epoch !== epochRef.current || dirtyRef.current) return
          setRunProgress(run)
          commitThread((prev) => upsertThink(prev, run.message))
        }, (note) => { if (epoch === epochRef.current) setConnectionNote(note) })
        halt()
        sessionStorage.removeItem(runStorageKey)
        activeRunRef.current = null
        assistLog(tid, 'llm.done')
        if (dirtyRef.current) continue
        if (outcome.status !== 'done' || !outcome.result) throw new Error(outcome.message)
        const data = outcome.result
        commitThread((prev) => {
          const thinkBot = [...prev].reverse().find((m) => m.role === 'bot' && !m.text)
          const done = thinkBot?.think?.live
            ? [...(thinkBot.think.done || []), thinkBot.think.live]
            : thinkBot?.think?.done || ['分析意图']
          return replaceThinkBot(prev, {
            role: 'bot',
            text: data.text,
            mid: tid,
            choices: data.choices,
            plan: data.plan ?? undefined,
            think: { done },
          })
        })
        break
      }
    } catch (err) {
      if (epoch !== epochRef.current) return
      failed = true
      if (err instanceof ApiError && err.status === 404) {
        activeRunRef.current = null
        sessionStorage.removeItem(runStorageKey)
      }
      const stopped = abortedRef.current
      const msg = stopped ? '已停止。' : err instanceof Error ? err.message : '对话失败'
      assistLog(midRef.current || '-', stopped ? 'stop' : 'fail', msg)
      commitThread((prev) => replaceThinkBot(prev, { role: 'bot', text: msg, mid: midRef.current }))
      setRecoverable(Boolean(activeRunRef.current))
    } finally {
      if (epoch !== epochRef.current) return
      loopingRef.current = false
      busyRef.current = false
      lockMergeRef.current = false
      abortRef.current = null
      setChatting(false)
      const last = threadRef.current[threadRef.current.length - 1]
      if (!failed && !abortedRef.current && last?.role === 'user') {
        queueMicrotask(() => {
          if (!loopingRef.current) void runLoop()
        })
      }
    }
  }

  useEffect(() => {
    activeRunRef.current = null
    agentConversationRef.current = false
    forcedRef.current = null
    threadRef.current = []
    setThread([])
    setChatting(false)
    setRecoverable(false)
    setRunProgress(null)
    const saved = sessionStorage.getItem(runStorageKey)
    if (saved) void runLoop(saved)
    return () => {
      epochRef.current++
      abortRef.current?.abort()
      loopingRef.current = false
      busyRef.current = false
    }
  }, [runStorageKey])

  const send = (text?: string) => {
    const content = (text ?? draft).trim()
    if (!content) return
    setDraft('')
    setPanel('home')
    if (!busyRef.current) midRef.current = newMsgId()
    const mid = midRef.current
    assistLog(mid, busyRef.current ? 'supplement' : 'send', content.slice(0, 80))
    if (busyRef.current) {
      if (lockMergeRef.current) {
        commitThread((prev) => [...prev, { role: 'user', text: content, mid }])
        return
      }
      dirtyRef.current = true
      if (activeRunRef.current) void assistantApi.cancelRun(activeRunRef.current).catch(() => undefined)
      commitThread((prev) => upsertThink([...prev, { role: 'user', text: content, mid }], '收到补充，正在结束旧请求后重新核对'))
      return
    }
    commitThread((prev) => upsertThink([...prev, { role: 'user', text: content, mid }], '分析意图'))
    void runLoop()
  }

  const runTask = (item: AssistantTask, extra?: Extra & { hoursDraft?: HoursDraft }) => {
    forcedRef.current = { tool: item.tool, path: item.path, extra }
    if (!busyRef.current) midRef.current = newMsgId()
    const mid = midRef.current
    assistLog(mid, 'task', item.tool)
    if (busyRef.current) {
      if (lockMergeRef.current) {
        commitThread((prev) => [...prev, { role: 'user', text: item.label, mid }])
        return
      }
      dirtyRef.current = true
      if (activeRunRef.current) void assistantApi.cancelRun(activeRunRef.current).catch(() => undefined)
      commitThread((prev) => upsertThink([...prev, { role: 'user', text: item.label, mid }], '收到补充，重新分析'))
      return
    }
    commitThread((prev) => upsertThink([...prev, { role: 'user', text: item.label, mid }], '分析意图'))
    void runLoop()
  }

  const confirmHours = (draft: HoursDraft) => {
    void runTask({ label: '确认写入课时', path: '/scheduling?tab=hours', tool: 'executeHours' }, { hoursDraft: draft })
  }

  const newChat = () => {
    if (activeRunRef.current) void assistantApi.cancelRun(activeRunRef.current).catch(() => undefined)
    epochRef.current++
    abortRef.current?.abort()
    activeRunRef.current = null
    sessionStorage.removeItem(runStorageKey)
    busyRef.current = false
    loopingRef.current = false
    setChatting(false)
    setRecoverable(false)
    setRunProgress(null)
    forcedRef.current = null
    dirtyRef.current = false
    threadRef.current = []
    setThread([])
    setDraft('')
    agentConversationRef.current = false
  }

  const helpItems = helpTab === 'faq' ? FAQ : helpTab === 'guide' ? GUIDES : STARTS
  const rotated = helpTab === 'faq' ? [...FAQ.slice(faqOffset), ...FAQ.slice(0, faqOffset)] : helpItems
  const filtered = rotated.filter((item) => !helpQuery.trim() || item.q.includes(helpQuery.trim()) || item.a.includes(helpQuery.trim()))
  const shownThread = thread.filter((msg) => !msg.text.startsWith('已到「'))

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
                className={`assist-dock-icon${panel === 'rate' ? ' is-on' : ''}`}
                title="满意度"
                onClick={() => toggle('rate')}
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

      {panel === 'rate' && (
        <section className="assist-help assist-help-slim" aria-label="满意度">
          <header className="assist-help-head">
            <strong>满意度</strong>
            <button type="button" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <p className="assist-sheet-cap">这次使用轻课堂助手，您打几星？</p>
          <div className="assist-rate">
            <StarPick
              value={satisfaction}
              onChange={(n) => {
                setSatisfaction(n)
                localStorage.setItem(RATE_KEY, String(n))
              }}
            />
            <span>{satisfaction ? STAR_HINT[satisfaction - 1] : '点选 1～5 星'}</span>
          </div>
        </section>
      )}

      {panel === 'home' && (
        <section className="assist-sheet" aria-label="轻课堂助手对话">
          <header className="assist-sheet-bar">
            <div className="assist-sheet-brand">
              <Face className="assist-sheet-face" />
              <div>
                <strong>轻课堂助手</strong>
                <span>当前在「{pageName}」</span>
              </div>
            </div>
            <button type="button" title="新对话" onClick={newChat}>
              <Icon name="plus" size={16} />
            </button>
            <button type="button" title="关闭" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <div className="assist-sheet-body">
            {shownThread.length === 0 && (
              <>
                <p className="assist-sheet-cap">
                  我可以核对本校排课准备情况、查询教师和规则，也能把你的排课要求整理成规则草稿，由你确认后保存。
                </p>
                <div className="assist-task-list">
                  <button type="button" className="assist-task" onClick={() => send('帮我检查本校排课准备情况，还缺什么？')}>
                    <Icon name="sparkles" size={16} /><span>检查排课准备情况</span><Icon name="chevron-right" size={16} />
                  </button>
                  <button type="button" className="assist-task" onClick={() => send('帮我添加数学禁排规则，先给我确认草稿')}>
                    <Icon name="sparkles" size={16} /><span>一起配置一条排课规则</span><Icon name="chevron-right" size={16} />
                  </button>
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
            {shownThread.length > 0 && (
              <div className="assist-thread">
                {shownThread.map((msg, i) => (
                  <div key={i} className={`assist-turn is-${msg.role}`}>
                    {msg.role === 'bot' && !msg.text && msg.think?.live ? <ThinkDial live={msg.think.live} progress={runProgress} connection={connectionNote} /> : null}
                    {msg.text ? (
                      <div className={`assist-bubble is-${msg.role}`}>
                        {msg.text}
                        {msg.mid ? <MidCopy id={msg.mid} /> : null}
                      </div>
                    ) : null}
                    {msg.role === 'bot' && msg.hoursDraft && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions">
                        <button type="button" className="is-ok" onClick={() => confirmHours(msg.hoursDraft!)}>
                          确认写入课时
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setThread((prev) => {
                              const next = [...prev]
                              next[i] = { role: 'bot', text: `${msg.text}\n已取消，未写入。` }
                              return next
                            })
                          }
                        >
                          取消
                        </button>
                      </div>
                    )}
                    {msg.role === 'bot' && msg.plan && (
                      <AssistantRulePlan
                        plan={msg.plan}
                        disabled={chatting || i !== shownThread.length - 1}
                        onChange={(plan) => commitThread((prev) => prev.map((item) => item.plan?.id === plan.id ? { ...item, plan } : item))}
                      />
                    )}
                    {msg.role === 'bot' && msg.choices && msg.choices.length > 0 && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions">
                        {msg.choices.map((item) => (
                          <button key={item.send} type="button" className="is-ok" onClick={() => send(item.send)}>
                            {item.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.role === 'bot' && msg.jumps && msg.jumps.length > 0 && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions">
                        {msg.jumps.map((item) => (
                          <button key={item.path + item.label} type="button" className="is-ok" onClick={() => navigate(item.path)}>
                            {item.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.role === 'bot' && msg.advice && i === shownThread.length - 1 ? (
                      <div className="assist-bubble is-bot assist-advice">{msg.advice}</div>
                    ) : null}
                    {msg.role === 'bot' && msg.awaitRules && i === shownThread.length - 1 && !msg.jumps?.length && (
                      <div className="assist-plan-actions">
                        <button
                          type="button"
                          onClick={() =>
                            setThread((prev) => [
                              ...prev,
                              {
                                role: 'bot',
                                text: '请在本页规则组勾选对应模板并绑定本校教师后点保存。',
                              },
                            ])
                          }
                        >
                          我去本页保存
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="assist-composer">
            <div className="assist-composer-row">
              <button type="button" className="assist-plus" title="新对话" aria-label="新对话" onClick={newChat}>
                <Icon name="plus" size={14} />
              </button>
              <textarea
                ref={composerRef}
                rows={1}
                value={draft}
                placeholder={chatting ? '思考中也可补充，会并入这一轮' : '排课、档案、设置，有问题都可以问'}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
              />
              <button
                type="button"
                className={`assist-send${chatting ? ' is-wait' : ''}`}
                disabled={!chatting && !draft.trim()}
                onClick={() => (chatting ? stopTurn() : send())}
                aria-label={chatting ? '停止' : '发送'}
                title={chatting ? '停止' : '发送'}
              >
                {chatting ? <i className="assist-send-dot" /> : <Icon name="send" size={13} />}
              </button>
            </div>
          </div>
          <p className="assist-here">{chatting ? '思考中 · 可补充' : `当前页 · ${pageName}`}</p>
          {recoverable && <button type="button" className="assist-task" onClick={() => activeRunRef.current && void runLoop(activeRunRef.current)}>恢复查看上次任务</button>}
        </section>
      )}
    </>
  )
}
