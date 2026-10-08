import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '@/api/http'
import { assistantApi, authApi, orgApi, schedulingApi, type AssistantExecution, type AssistantPlan, type AssistantRun } from '@/api'
import { watchAssistantRun } from '@/assistant/task'
import { assistantPageContext } from '@/assistant/context'
import { useAuthStore } from '@/store/auth'
import AssistantRulePlan from '@/components/AssistantRulePlan'
import AssistantAddMenu from '@/components/AssistantAddMenu'
import { MATERIAL_ACCEPT, mergeMaterials, materialsForTurn, type AssistantMaterial } from '@/assistant/materials'
import { canUsePageActions, modeForTurn, type AssistantMode } from '@/assistant/mode'
import AssistMarkdown from '@/components/AssistMarkdown'
import Icon from '@/components/Icon'
import { type HoursDraft } from '@/assistant/hoursPlan'
import { runAssistantTool, type JumpLink, type ToolExtra } from '@/assistant/run'
import { assistLog, newMsgId } from '@/assistant/trace'
import { hereOf, jumpLabel, placeLabel, samePlace } from '@/assistant/place'
import { decideJumpReply } from '@/assistant/jump-intent'
import { classifyPageIntent, executeSubjectPageTask, prepareSubject } from '@/assistant/pageSubjectAgent'
import { isSubjectCreationRequest, isSubjectChoiceReply, isSubjectTaskCancellation, mayRequestPageAction, readExplicitSubjectName, readPendingSubjectDraft, type SubjectDraft } from '@/assistant/subjectTask'
import { pageSnapshot, type AssistantTask } from '@/assistant/skills'
import './assistant-dock.css'

const DOCK_KEY = 'zh_assistant_dock_collapsed'
const STAR_HINT = ['很不满意', '不满意', '一般', '满意', '非常满意']
const RATE_KEY = 'zh_assistant_satisfaction'
const THREAD_LIMIT = 30

type ChatMsg = {
  role: 'user' | 'bot'
  text: string
  mid?: string
  hoursDraft?: HoursDraft
  plan?: AssistantPlan
  awaitRules?: boolean
  jumps?: JumpLink[]
  advice?: string
  choices?: { label: string; send: string; act?: () => void }[]
  think?: { done: string[]; live?: string }
  execution?: AssistantExecution
  /** False for transport/recovery/degraded UI notices that must not enter an LLM prompt. */
  modelVisible?: boolean
  materials?: AssistantMaterial[]
  assistantMode?: AssistantMode
}

function InboxTaskBar({
  chatting,
  show,
  message,
  onSteer,
}: {
  chatting: boolean
  show: boolean
  message: string
  onSteer: () => void
}) {
  // 任务条属于“调整方向”交互，只在用户已经追加消息后出现。
  // 首条消息运行时保持对话区干净，避免把普通问候误显示成持续任务。
  if (!show || !chatting) return null
  return (
    <div className="assist-inbox-taskbar" role="status" aria-live="polite">
      <span className="assist-inbox-task-label" title={message}>
        <Icon name="sparkles" size={14} />
        {message}
      </span>
      <button type="button" className="assist-inbox-steer" onClick={onSteer}>
        <Icon name="arrow-right" size={13} />
        调整方向
      </button>
    </div>
  )
}

function storedThread(key: string): ChatMsg[] {
  try {
    const raw = JSON.parse(localStorage.getItem(key) || '[]') as unknown
    if (!Array.isArray(raw)) return []
    const restored = raw.slice(-THREAD_LIMIT).flatMap((item): ChatMsg[] => {
      if (!item || typeof item !== 'object') return []
      const value = item as Record<string, unknown>
      if ((value.role !== 'user' && value.role !== 'bot') || typeof value.text !== 'string' || !value.text.trim()) return []
      return [{
        role: value.role,
        text: value.text.slice(0, 8000),
        mid: typeof value.mid === 'string' ? value.mid.slice(0, 80) : undefined,
        modelVisible: value.modelVisible !== false,
        execution: readExecution(value.execution),
      }]
    })
    const seen = new Set<string>()
    return restored.filter((item) => {
      const identity = `${item.role}:${item.mid || ''}:${item.text}`
      if (seen.has(identity)) return false
      seen.add(identity)
      return true
    })
  } catch {
    return []
  }
}

function rememberThread(key: string, messages: ChatMsg[]) {
  const safe = messages
    .filter((message) => message.text.trim())
    .slice(-THREAD_LIMIT)
    .map((message) => ({
      role: message.role,
      text: (message.plan ? `${message.text}\n\n${message.plan.summary}` : message.text).slice(0, 8000),
      mid: message.mid,
      modelVisible: message.modelVisible !== false,
      execution: message.execution,
    }))
  try {
    localStorage.setItem(key, JSON.stringify(safe))
  } catch {
    // Storage can be unavailable or full; the live conversation must keep working.
  }
}

function readExecution(raw: unknown): AssistantExecution | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  if (!['direct', 'agent', 'supervisor'].includes(String(value.mode))) return undefined
  const tasks: AssistantExecution['tasks'] = Array.isArray(value.tasks) ? value.tasks.slice(0, 5).flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const task = item as Record<string, unknown>
    if (typeof task.id !== 'string' || typeof task.label !== 'string' || !['running', 'succeeded', 'failed'].includes(String(task.status))) return []
    return [{
      id: task.id.slice(0, 40),
      label: task.label.slice(0, 40),
      status: task.status as AssistantExecution['tasks'][number]['status'],
      attempt: typeof task.attempt === 'number' ? task.attempt : undefined,
      retry_count: typeof task.retry_count === 'number' ? task.retry_count : undefined,
      allowed_tools: Array.isArray(task.allowed_tools) ? task.allowed_tools.filter((tool): tool is string => typeof tool === 'string').slice(0, 8) : undefined,
    }]
  }) : []
  return {
    mode: value.mode as AssistantExecution['mode'],
    multi_agent: value.multi_agent === true,
    kind: value.kind === 'readiness' || value.kind === 'diagnosis' ? value.kind : null,
    tasks,
  }
}

function ExecutionBadge({ execution }: { execution?: AssistantExecution }) {
  if (!execution || execution.mode === 'pending' || execution.tasks.length === 0) return null
  const label = execution.mode === 'supervisor'
    ? execution.kind === 'diagnosis' ? '排课诊断' : '排课准备'
    : '检查进度'
  const statusText = (status: AssistantExecution['tasks'][number]['status']) => status === 'succeeded' ? '完成' : status === 'failed' ? '失败' : '进行中'
  return (
    <details className="assist-execution" aria-label="检查进度">
      <summary>{label} · {execution.tasks.filter((task) => task.status === 'succeeded').length}/{execution.tasks.length} 项完成{execution.tasks.some((task) => task.status === 'failed') ? ' · 有失败项' : ''}</summary>
      <ul aria-label="检查项状态">
        {execution.tasks.map((task) => <li key={task.id}>{task.label} · {statusText(task.status)}</li>)}
      </ul>
    </details>
  )
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
    <div className={`assist-dial is-live${progress ? ' has-progress' : ''}`}>
      <span className="assist-dial-kicker">处理进度</span>
      <div className="assist-dial-window" aria-live="polite">
        <div key={live} className="assist-dial-face">
          {live}
        </div>
      </div>
      {progress && <div className="assist-progress-detail">
        <ExecutionBadge execution={progress.execution} />
        <span>已等待 {progress.elapsed_seconds} 秒 · 当前阶段 {progress.phase_elapsed_seconds} 秒</span>
        <span>{connection || (heartbeatRecent ? '后台仍在响应' : '暂未收到新的后台心跳，正在核对状态')}</span>
        {progress.phase_elapsed_seconds >= 15 && <span>当前阶段暂未返回新结果。你可以继续使用其他页面，或停止本轮处理。</span>}
        <details><summary>查看执行记录</summary><ol>{(progress.events ?? []).map((event, i) => <li key={i}>{event.message}</li>)}</ol></details>
      </div>}
      {!progress && connection && <div role="status">{connection}</div>}
    </div>
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
  const schoolCode = useAuthStore((s) => s.schoolCode)
  const userId = useAuthStore((s) => s.user?.id)
  const threadStorageKey = `lc-assistant-thread:${schoolCode}:${userId ?? 'anonymous'}`
  const runStorageKey = `lc-assistant-run:${schoolCode}:${userId ?? 'anonymous'}`
  const subjectStorageKey = `lc-assistant-subject:v2:${schoolCode}:${userId ?? 'anonymous'}`
  const modeStorageKey = `lc-assistant-mode:${schoolCode}:${userId ?? 'anonymous'}`
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(DOCK_KEY) === '1')
  const [panel, setPanel] = useState<Panel>(null)
  const [noticeUnread, setNoticeUnread] = useState(true)
  const [draft, setDraft] = useState('')
  const [assistantMode, setAssistantMode] = useState<AssistantMode>('standard')
  const modeRef = useRef<AssistantMode>('standard')
  const changeMode = (mode: AssistantMode) => {
    modeRef.current = mode
    setAssistantMode(mode)
    sessionStorage.setItem(modeStorageKey, mode)
  }
  const [materials, setMaterials] = useState<AssistantMaterial[]>([])
  const [readingFiles, setReadingFiles] = useState(false)
  const [materialError, setMaterialError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const uploadRef = useRef<AbortController | null>(null)
  const materialsRef = useRef<AssistantMaterial[]>([])

  const updateMaterials = (items: AssistantMaterial[]) => {
    materialsRef.current = items
    setMaterials(items)
  }
  const readFiles = async (files: File[]) => {
    if (readingFiles || busyRef.current || !files.length) return
    setMaterialError('')
    if (files.length + materialsRef.current.length > 8) {
      setMaterialError('每条消息最多添加 8 个文件；请缩小文件夹或分批选择')
      return
    }
    const controller = new AbortController()
    uploadRef.current = controller
    setReadingFiles(true)
    const errors: string[] = []
    try {
      for (const file of files) {
        try {
          const material = await assistantApi.readAttachment(file, controller.signal)
          if (controller.signal.aborted) return
          // Relative folder names are display data, never server filesystem paths.
          material.name = (file.webkitRelativePath || material.name).slice(0, 200)
          updateMaterials(mergeMaterials(materialsRef.current, [material]))
        } catch (error) {
          if (controller.signal.aborted) return
          errors.push(`${file.name}：${error instanceof Error ? error.message : '读取失败'}`)
        }
      }
      setMaterialError(errors.join('；'))
    } finally {
      if (uploadRef.current === controller) {
        uploadRef.current = null
        setReadingFiles(false)
      }
    }
  }
  const [thread, setThread] = useState<ChatMsg[]>(() => storedThread(threadStorageKey))
  const [conversationReady, setConversationReady] = useState(false)
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
  const [themeMode, setThemeMode] = useState<'minimal' | 'tech'>(() => {
    return localStorage.getItem('zh_theme') === 'tech' ? 'tech' : 'minimal'
  })

  useEffect(() => {
    document.body.dataset.theme = themeMode
    localStorage.setItem('zh_theme', themeMode)
  }, [themeMode])
  const threadRef = useRef<ChatMsg[]>(thread)
  const busyRef = useRef(false)
  const dirtyRef = useRef(false)
  const lockMergeRef = useRef(false)
  const forcedRef = useRef<{ tool: AssistantTask['tool']; path?: string; extra?: ToolExtra } | null>(null)
  const midRef = useRef('')
  const agentConversationRef = useRef(false)
  const subjectDraftRef = useRef<SubjectDraft | null>(null)
  const subjectRunningRef = useRef(false)
  const activeRunRef = useRef<string | null>(null)
  const epochRef = useRef(0)
  const [runProgress, setRunProgress] = useState<AssistantRun | null>(null)
  const [connectionNote, setConnectionNote] = useState('')
  const [recoverable, setRecoverable] = useState(false)
  const [steerVisible, setSteerVisible] = useState(false)
  const [latestSteer, setLatestSteer] = useState('')
  const commitThread = (updater: (prev: ChatMsg[]) => ChatMsg[]) => {
    const next = updater(threadRef.current)
    threadRef.current = next
    setThread(next)
    rememberThread(threadStorageKey, next)
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
  const messageBodyRef = useRef<HTMLDivElement>(null)
  const followLatestRef = useRef(true)
  const abortRef = useRef<AbortController | null>(null)
  const abortedRef = useRef(false)

  const stopTurn = () => {
    if (subjectRunningRef.current) {
      abortRef.current?.abort()
      return
    }
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
    setSteerVisible(false)
    setLatestSteer('')
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
        const withTrace = (extra?: ToolExtra) => ({ ...extra, here: hereNow, traceId: tid })
        const turnMode = modeForTurn(threadRef.current, modeRef.current)
        const previousAnswer = [...threadRef.current].reverse().find((item) => item.role === 'bot' && item.text)
        const jumpDecision = previousAnswer?.jumps ? decideJumpReply(merged, previousAnswer.jumps) : { kind: 'none' as const }
        if (jumpDecision.kind === 'confirm') {
          const target = placeLabel(jumpDecision.jump.path)
          assistLog(tid, 'jump.confirm', jumpDecision.jump.path)
          navigate(jumpDecision.jump.path)
          commitThread((prev) => replaceThinkBot(prev, {
            role: 'bot',
            text: `好的，已为你打开「${target}」。可以继续问我这个页面怎么操作。`,
            mid: tid,
          }))
          break
        }
        if (jumpDecision.kind === 'cancel') {
          assistLog(tid, 'jump.cancel', hereNow)
          commitThread((prev) => replaceThinkBot(prev, {
            role: 'bot',
            text: '好的，先留在当前页面。需要继续时告诉我。',
            mid: tid,
          }))
          break
        }
        const forced = forcedRef.current
        forcedRef.current = null
        if (forced && canUsePageActions(turnMode)) {
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
        // 自由文本统一交给后端 AssistantGateway。页面上的明确任务按钮仍通过
        // forcedRef 调用确定性工具，避免前后端各维护一套关键词意图路由。
        assistLog(tid, 'route', 'gateway')
        halt()
        if (dirtyRef.current) continue
        commitThread((prev) => upsertThink(prev, resumeId ? '正在恢复上次任务状态' : '已收到，正在提交任务'))
        agentConversationRef.current = true
        const history = threadRef.current.filter((m) => m.text && m.modelVisible !== false)
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
              model_visible: m.modelVisible !== false,
            })),
            page_title: pageName,
            page_path: hereNow,
            page_context: { ...assistantPageContext(hereNow), assistant_mode: turnMode, reference_materials: materialsForTurn(history) },
            can: snap.can,
            cannot: snap.cannot,
            message_id: tid,
          }, abortRef.current?.signal)
        if (dirtyRef.current) void assistantApi.cancelRun(runId).catch(() => undefined)
        resumeId = undefined
        halt()
        const outcome = await watchAssistantRun(runId, abortRef.current!.signal, (run) => {
          if (epoch !== epochRef.current || dirtyRef.current) return
          const terminal = !['queued', 'running'].includes(run.status)
          setRunProgress(terminal ? null : run)
          if (!terminal) commitThread((prev) => upsertThink(prev, run.message))
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
            execution: outcome.execution,
            choices: data.choices,
            plan: data.plan ?? undefined,
            jumps: data.jumps,
            think: { done },
            modelVisible: data.model_visible !== false,
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
      commitThread((prev) => {
        // 恢复查看同一个 run 时不要重复追加相同错误气泡，避免重试改变对话布局。
        if (prev.some((item) => item.role === 'bot' && item.text === msg)) return prev
        return replaceThinkBot(prev, {
          role: 'bot', text: msg, mid: midRef.current, modelVisible: false,
        })
      })
      setRecoverable(Boolean(activeRunRef.current))
    } finally {
      if (epoch !== epochRef.current) return
      loopingRef.current = false
      busyRef.current = false
      lockMergeRef.current = false
      abortRef.current = null
      setChatting(false)
      setSteerVisible(false)
      setLatestSteer('')
      const last = threadRef.current[threadRef.current.length - 1]
      if (!failed && !abortedRef.current && last?.role === 'user') {
        queueMicrotask(() => {
          if (!loopingRef.current) void runLoop()
        })
      }
    }
  }

  useEffect(() => {
    abortRef.current?.abort()
    uploadRef.current?.abort()
    updateMaterials([])
    setReadingFiles(false)
    setMaterialError('')
    changeMode(sessionStorage.getItem(modeStorageKey) === 'plan' ? 'plan' : 'standard')
    subjectDraftRef.current = readPendingSubjectDraft(sessionStorage.getItem(subjectStorageKey))
    subjectRunningRef.current = false
    epochRef.current++
    busyRef.current = false
    activeRunRef.current = null
    agentConversationRef.current = false
    forcedRef.current = null
    const restored = storedThread(threadStorageKey)
    threadRef.current = restored
    setThread(restored)
    setConversationReady(false)
    agentConversationRef.current = false
    setChatting(false)
    setRecoverable(false)
    setRunProgress(null)
    const saved = sessionStorage.getItem(runStorageKey)
    if (saved) void runLoop(saved)
    let disposed = false
    void assistantApi.conversation().then((remote) => {
      if (disposed) return
      if (remote.messages.length) {
        const restoredRemote: ChatMsg[] = remote.messages.map((item) => ({
          role: item.role === 'assistant' ? 'bot' : 'user',
          text: item.content,
          modelVisible: item.model_visible !== false,
          execution: restored.find((saved) => saved.role === (item.role === 'assistant' ? 'bot' : 'user') && saved.text === item.content)?.execution,
        }))
        threadRef.current = restoredRemote
        setThread(restoredRemote)
        rememberThread(threadStorageKey, restoredRemote)
      } else if (restored.length) {
        void assistantApi.saveConversation(restored.map((item) => ({
          role: item.role === 'bot' ? 'assistant' : 'user',
          content: item.text,
          model_visible: item.modelVisible !== false,
        }))).catch(() => undefined)
      }
      setConversationReady(true)
    }).catch(() => {
      if (!disposed) setConversationReady(true)
    })
    return () => {
      disposed = true
      epochRef.current++
      abortRef.current?.abort()
      loopingRef.current = false
      busyRef.current = false
    }
  }, [runStorageKey, threadStorageKey])

  useEffect(() => {
    if (!conversationReady) return
    const messages = thread
      .filter((item) => item.text.trim())
      .slice(-60)
      .map((item) => ({
        role: item.role === 'bot' ? 'assistant' as const : 'user' as const,
        content: (item.plan ? `${item.text}\n\n${item.plan.summary}` : item.text).slice(0, 8000),
        model_visible: item.modelVisible !== false,
      }))
    const timer = window.setTimeout(() => {
      void assistantApi.saveConversation(messages).catch(() => undefined)
    }, 350)
    return () => window.clearTimeout(timer)
  }, [conversationReady, thread])

  const runSubjectConversation = async (content: string, mid: string) => {
    const epoch = epochRef.current
    const controller = new AbortController()
    abortRef.current = controller
    subjectRunningRef.current = true
    busyRef.current = true
    setChatting(true)
    const progress = (message: string) => {
      if (epoch === epochRef.current) commitThread(prev => upsertThink(prev, message))
    }
    try {
      // Keep explicit user input even if preparation fails, so the next reply
      // stays in the subject workflow instead of becoming an ordinary chat.
      const explicitName = readExplicitSubjectName(content)
      if (explicitName) {
        subjectDraftRef.current = { ...subjectDraftRef.current, name: explicitName,
          course_type: subjectDraftRef.current?.course_type ?? null,
          evening_study_allowed: subjectDraftRef.current?.evening_study_allowed ?? null }
        sessionStorage.setItem(subjectStorageKey, JSON.stringify(subjectDraftRef.current))
      }
      const prepared = await prepareSubject(content, subjectDraftRef.current, controller.signal)
      controller.signal.throwIfAborted()
      subjectDraftRef.current = prepared.status === 'needs_input' ? prepared.draft : null
      if (subjectDraftRef.current) sessionStorage.setItem(subjectStorageKey, JSON.stringify(subjectDraftRef.current))
      else sessionStorage.removeItem(subjectStorageKey)
      const text = prepared.status === 'ready'
        ? await executeSubjectPageTask(prepared, navigate, controller.signal, progress)
        : prepared.text
      if (epoch === epochRef.current) commitThread(prev => replaceThinkBot(prev, { role: 'bot', text, mid }))
    } catch (error) {
      if (epoch === epochRef.current) commitThread(prev => replaceThinkBot(prev, {
        role: 'bot', mid, modelVisible: false,
        text: controller.signal.aborted ? '已停止页面操作。已提交的保存可能仍会完成，请核对科目列表。'
          : error instanceof Error ? error.message : '页面操作失败，请重试。',
      }))
    } finally {
      if (epoch === epochRef.current) {
        subjectRunningRef.current = false
        busyRef.current = false
        setChatting(false)
        abortRef.current = null
      }
    }
  }

  const runPageIntentConversation = async (content: string, mid: string) => {
    const controller = new AbortController()
    abortRef.current = controller
    busyRef.current = true
    setChatting(true)
    try {
      const intent = await classifyPageIntent(content, controller.signal)
      if (controller.signal.aborted) {
        commitThread(prev => replaceThinkBot(prev, { role: 'bot', text: '已停止意图识别。', mid }))
        abortRef.current = null
        busyRef.current = false
        setChatting(false)
        return
      }
      if (intent === 'create_subject') {
        void runSubjectConversation(content, mid)
        return
      }
      commitThread(prev => replaceThinkBot(prev, { role: 'bot', text: '', mid }))
      abortRef.current = null
      busyRef.current = false
      setChatting(false)
      void runLoop()
    } catch {
      if (controller.signal.aborted) {
        commitThread(prev => replaceThinkBot(prev, { role: 'bot', text: '已停止意图识别。', mid }))
        abortRef.current = null
        busyRef.current = false
        setChatting(false)
        return
      }
      // Keep existing chat available if intent detection/model routing fails.
      commitThread(prev => replaceThinkBot(prev, { role: 'bot', text: '', mid }))
      abortRef.current = null
      busyRef.current = false
      setChatting(false)
      void runLoop()
    }
  }

  const send = (text?: string) => {
    const content = (text ?? draft).trim()
    if (!content || readingFiles) return
    const attached = materialsRef.current
    const hasMaterials = attached.length > 0 || materialsForTurn(threadRef.current).length > 0
    if (attached.length && subjectDraftRef.current && canUsePageActions(modeRef.current)) {
      setMaterialError('请先完成或取消当前科目草稿，再发送附件')
      return
    }
    const userMessage: ChatMsg = { role: 'user', text: content, assistantMode: modeRef.current, materials: attached.length ? attached : undefined }
    updateMaterials([])
    setMaterialError('')
    followLatestRef.current = true
    setDraft('')
    setPanel('home')
    if (!busyRef.current) midRef.current = newMsgId()
    const mid = busyRef.current ? newMsgId() : midRef.current
    if (subjectRunningRef.current) {
      if (isSubjectTaskCancellation(content)) stopTurn()
      else commitThread(prev => [...prev, { role: 'bot', text: '科目操作正在进行，请先停止当前操作，再提供新的要求。', modelVisible: false }])
      return
    }
    if (canUsePageActions(modeRef.current) && !busyRef.current && !subjectDraftRef.current && isSubjectChoiceReply(content)) {
      const lastUser = [...threadRef.current].reverse().find(item => item.role === 'user')
      const name = lastUser && isSubjectCreationRequest(lastUser.text) ? readExplicitSubjectName(lastUser.text) : null
      if (name) subjectDraftRef.current = { name, course_type: null, evening_study_allowed: null }
    }
    if (canUsePageActions(modeRef.current) && !busyRef.current && subjectDraftRef.current) {
      if (isSubjectTaskCancellation(content)) {
        subjectDraftRef.current = null
        sessionStorage.removeItem(subjectStorageKey)
        commitThread(prev => [...prev, { ...userMessage, mid }, { role: 'bot', text: '已取消新增科目。', mid }])
        return
      }
      commitThread(prev => upsertThink([...prev, { ...userMessage, mid }], '正在校验科目数据'))
      void runSubjectConversation(content, mid)
      return
    }
    if (canUsePageActions(modeRef.current) && !busyRef.current && !hasMaterials && mayRequestPageAction(content)) {
      commitThread(prev => upsertThink([...prev, { ...userMessage, mid }], '正在识别操作意图'))
      void runPageIntentConversation(content, mid)
      return
    }
    assistLog(mid, busyRef.current ? 'steer' : 'followup', content.slice(0, 80))
    if (busyRef.current) {
      const runId = activeRunRef.current
      if (!runId || lockMergeRef.current) {
        commitThread((prev) => [...prev, { ...userMessage, mid }])
        return
      }
      setSteerVisible(true)
      setLatestSteer(content)
      commitThread((prev) => {
        const next = [...prev]
        let pending = -1
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].role === 'bot' && !next[i].text) {
            pending = i
            break
          }
        }
        if (pending >= 0) next.splice(pending, 1)
        return upsertThink([...next, { ...userMessage, mid }], '已收到方向调整，将在下一步处理')
      })
      void assistantApi.steerRun(runId, content).catch((err) => {
        if (err instanceof ApiError && err.status === 409) {
          // run 恰好结束时，把消息留给下一 Turn，不丢失用户输入。
          dirtyRef.current = true
          setConnectionNote('当前任务刚刚结束，正在作为后续任务继续处理')
          return
        }
        setConnectionNote('方向调整暂时未送达，请稍后重试')
      })
      return
    }
    commitThread((prev) => upsertThink([...prev, { ...userMessage, mid }], '分析意图'))
    void runLoop()
  }

  const pushMsg = (msg: ChatMsg) => commitThread((prev) => [...prev, msg])

  const runTask = (item: AssistantTask, extra?: ToolExtra) => {
    if (!canUsePageActions(modeRef.current)) { send(item.label); return }
    followLatestRef.current = true
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
    changeMode('standard')
    uploadRef.current?.abort()
    updateMaterials([])
    setMaterialError('')
    setReadingFiles(false)
    if (activeRunRef.current) void assistantApi.cancelRun(activeRunRef.current).catch(() => undefined)
    epochRef.current++
    subjectDraftRef.current = null
    sessionStorage.removeItem(subjectStorageKey)
    subjectRunningRef.current = false
    abortRef.current?.abort()
    activeRunRef.current = null
    sessionStorage.removeItem(runStorageKey)
    busyRef.current = false
    loopingRef.current = false
    setChatting(false)
    setRecoverable(false)
    setRunProgress(null)
    setSteerVisible(false)
    setLatestSteer('')
    forcedRef.current = null
    dirtyRef.current = false
    threadRef.current = []
    setThread([])
    localStorage.removeItem(threadStorageKey)
    void assistantApi.clearConversation().catch(() => undefined)
    setDraft('')
    agentConversationRef.current = false
  }

  // 配置规则向导：科目/年级取自本校课时与组织数据，选完再进草稿流程，不花模型调用。
  const onRuleSubject = (subject: string, grades: string[]) => {
    if (busyRef.current) return
    pushMsg({ role: 'user', text: subject })
    if (!grades.length) {
      pushMsg({
        role: 'bot',
        text: '系统里还没有年级。先到行政班建好年级，再回来配规则。',
        jumps: [{ label: '去行政班', path: '/classes' }],
      })
      return
    }
    pushMsg({
      role: 'bot',
      text: `第二步，${subject}的规则配给哪个年级？（之后我会问你星期节次等细节）`,
      choices: grades.slice(0, 8).map((grade) => ({
        label: grade,
        send: `给${grade}的${subject}配置一条排课规则，先给我确认草稿`,
      })),
    })
  }

  const startRuleWizard = () => {
    if (!canUsePageActions(modeRef.current)) { send('帮我规划一条排课规则，先给方案'); return }
    setPanel('home')
    if (busyRef.current) return
    if (!busyRef.current) midRef.current = newMsgId()
    const mid = midRef.current
    assistLog(mid, 'task', 'ruleWizard')
    commitThread((prev) => upsertThink([...prev, { role: 'user', text: '一起配置一条排课规则', mid }], '读取本校课时科目和年级'))
    void (async () => {
      try {
        const years = await authApi.academicYears()
        const year = years.current_academic_year
        const term = years.current_term || '1'
        const hours = year ? await schedulingApi.courseHours({ academic_year: year, term }) : []
        const names: string[] = []
        for (const row of hours) {
          if ((row.weekday_periods || 0) <= 0 || !row.subject_name) continue
          if (!names.includes(row.subject_name)) names.push(row.subject_name)
        }
        const gradeNames = (await orgApi.grades()).map((g) => g.name).filter(Boolean)
        if (!names.length) {
          commitThread((prev) => replaceThinkBot(prev, {
            role: 'bot',
            text: '本校课时里还没有科目周节数。规则建立在课时之上，先到课时管理把各科每周节数填好，再回来配规则。',
            jumps: [{ label: '去课时管理', path: '/scheduling?tab=hours' }],
            think: { done: ['读取本校课时科目和年级'] },
          }))
          return
        }
        commitThread((prev) => replaceThinkBot(prev, {
          role: 'bot',
          text: `好。第一步，选科目（来自本校课时已建的 ${names.length} 门科目）：`,
          choices: names.slice(0, 10).map((name) => ({
            label: name,
            send: `选${name}`,
            act: () => onRuleSubject(name, gradeNames),
          })),
          think: { done: ['读取本校课时科目和年级'] },
        }))
      } catch {
        commitThread((prev) => replaceThinkBot(prev, {
          role: 'bot',
          text: '读取本校科目和年级失败，请稍后再试。',
          think: { done: ['读取本校课时科目和年级'] },
        }))
      }
    })()
  }

  const helpItems = helpTab === 'faq' ? FAQ : helpTab === 'guide' ? GUIDES : STARTS
  const rotated = helpTab === 'faq' ? [...FAQ.slice(faqOffset), ...FAQ.slice(0, faqOffset)] : helpItems
  const filtered = rotated.filter((item) => !helpQuery.trim() || item.q.includes(helpQuery.trim()) || item.a.includes(helpQuery.trim()))
  const shownThread = thread.filter((msg) => !msg.text.startsWith('已到「'))

  useLayoutEffect(() => {
    if (panel !== 'home' || !followLatestRef.current) return
    const body = messageBodyRef.current
    if (body) body.scrollTop = body.scrollHeight
  }, [panel, thread, runProgress, connectionNote])

  useEffect(() => {
    if (panel !== 'home') return
    followLatestRef.current = true
    const frame = window.requestAnimationFrame(() => {
      const body = messageBodyRef.current
      if (body) body.scrollTop = body.scrollHeight
    })
    return () => window.cancelAnimationFrame(frame)
  }, [panel])

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
                    <button type="button" onClick={() => { setPanel('home'); commitThread(() => [{ role: 'bot', text: '使用上卡住了可以说页面和操作。排课、账号、导入都可以问。' }]) }}>
                      <strong>使用咨询</strong>
                      <span>排课、账号、导入怎么配，按当前学校说明</span>
                    </button>
                    <button type="button" onClick={() => { setPanel('home'); commitThread(() => [{ role: 'bot', text: '生成失败或导入报错，把提示原文发过来。后台任务请看 Celery 日志。' }]) }}>
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
              <button
                type="button"
                className="assist-dock-icon"
                title={themeMode === 'tech' ? '切换到极简主题' : '切换到科技主题'}
                aria-label={themeMode === 'tech' ? '切换到极简主题' : '切换到科技主题'}
                onClick={() => setThemeMode((current) => (current === 'tech' ? 'minimal' : 'tech'))}
              >
                <Icon name={themeMode === 'tech' ? 'dashboard' : 'sparkles'} size={20} />
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
                <span>{pageName}</span>
              </div>
            </div>
            <button type="button" title="新对话" onClick={newChat}>
              <Icon name="plus" size={16} />
            </button>
            <button type="button" title="关闭" onClick={() => setPanel(null)}>
              <Icon name="x" size={16} />
            </button>
          </header>
          <div
            ref={messageBodyRef}
            className="assist-sheet-body"
            onScroll={(event) => {
              const body = event.currentTarget
              followLatestRef.current = body.scrollHeight - body.scrollTop - body.clientHeight <= 48
            }}
          >
            {shownThread.length === 0 && (
              <>
                <p className="assist-sheet-cap">
                  我可以核对本校排课准备情况、查询教师和规则，也能把你的排课要求整理成规则草稿，由你确认后保存。
                </p>
                <div className="assist-task-list">
                  <button type="button" className="assist-task" onClick={() => send('帮我检查本校排课准备情况，还缺什么？')}>
                    <Icon name="sparkles" size={16} /><span>检查排课准备情况</span><Icon name="chevron-right" size={16} />
                  </button>
                  <button type="button" className="assist-task" onClick={() => startRuleWizard()}>
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
                        {msg.role === 'bot' && <ExecutionBadge execution={msg.execution} />}
                        {msg.role === 'bot' ? <AssistMarkdown text={msg.text} /> : msg.text}
                        {msg.role === 'user' && msg.assistantMode === 'plan' && <small className="assist-turn-mode">计划模式</small>}
                        {msg.role === 'user' && msg.materials?.length ? <div className="assist-sent-materials">{msg.materials.map(item => <span key={item.id}><Icon name="file-text" size={12} />{item.name}</span>)}</div> : null}
                      </div>
                    ) : null}
                    {msg.role === 'bot' && msg.hoursDraft && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions">
                        <button type="button" className="is-ok" disabled={assistantMode === 'plan'} onClick={() => confirmHours(msg.hoursDraft!)}>
                          确认写入课时
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            commitThread((prev) => {
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
                        disabled={chatting || assistantMode === 'plan' || i !== shownThread.length - 1}
                        onChange={(plan) => commitThread((prev) => prev.map((item) => item.plan?.id === plan.id ? { ...item, plan } : item))}
                      />
                    )}
                    {msg.role === 'bot' && msg.choices && msg.choices.length > 0 && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions">
                        {msg.choices.map((item) => (
                          <button
                            key={item.send || item.label}
                            type="button"
                            className="is-ok"
                            onClick={() => {
                              if (item.act) {
                                item.act()
                                return
                              }
                              send(item.send)
                            }}
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.role === 'bot' && msg.jumps && msg.jumps.length > 0 && i === shownThread.length - 1 && (
                      <div className="assist-plan-actions assist-jump-actions" aria-label="建议的下一步">
                        <div className="assist-jump-question">
                          <strong>需要我帮你跳转吗？</strong>
                          <span>点击下方按钮，或直接回复“好”</span>
                        </div>
                        {msg.jumps.map((item) => (
                          <button
                            key={item.path + item.label}
                            type="button"
                            className="assist-jump-action"
                            aria-label={`打开「${placeLabel(item.path)}」`}
                            onClick={() => navigate(item.path)}
                          >
                            <span className="assist-jump-copy">
                              <small>{item.path.split('?')[0] === location.pathname ? '确认操作 · 切换页签' : '确认操作 · 打开页面'}</small>
                              <strong>打开「{placeLabel(item.path)}」</strong>
                            </span>
                            <span className="assist-jump-arrow"><Icon name="arrow-right" size={16} /></span>
                          </button>
                        ))}
                      </div>
                    )}
                    {msg.role === 'bot' && msg.advice && i === shownThread.length - 1 ? (
                      <div className="assist-bubble is-bot assist-advice">
                        <AssistMarkdown text={msg.advice} />
                      </div>
                    ) : null}
                    {msg.role === 'bot' && msg.awaitRules && i === shownThread.length - 1 && !msg.jumps?.length && (
                      <div className="assist-plan-actions">
                        <button
                          type="button"
                          onClick={() =>
                            commitThread((prev) => [
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
          <InboxTaskBar
            chatting={chatting}
            show={steerVisible}
            message={latestSteer}
            onSteer={() => {
              setConnectionNote('请输入新的处理方向，发送后将用于下一步')
              composerRef.current?.focus()
            }}
          />
          <div className={`assist-composer${materials.length || materialError || readingFiles ? ' has-materials' : ''}`}>
            {assistantMode === 'plan' && <div className="assist-mode-chip" role="status"><Icon name="clipboard" size={14} /><span>计划模式 · 只分析</span><button type="button" aria-label="退出计划模式" disabled={chatting} onClick={() => changeMode('standard')}><Icon name="x" size={12} /></button></div>}
            <input type="file" hidden ref={fileInputRef} multiple accept={MATERIAL_ACCEPT} aria-label="选择助手附件"
              onChange={event => { void readFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
            <input type="file" hidden ref={folderInputRef} multiple {...{ webkitdirectory: '', directory: '' }} aria-label="选择附件文件夹"
              onChange={event => { void readFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
            {materials.length > 0 && <div className="assist-materials" aria-label="待发送附件">
              {materials.map(item => <div key={item.id} className="assist-material" title={item.name}>
                <Icon name="file-text" size={14} /><span>{item.name}{item.truncated ? '（已截取）' : ''}</span>
                <button type="button" aria-label={`移除 ${item.name}`} onClick={() => updateMaterials(materialsRef.current.filter(value => value.id !== item.id))}><Icon name="x" size={12} /></button>
              </div>)}
            </div>}
            {readingFiles && <p className="assist-material-status" role="status">正在读取附件…</p>}
            {materialError && <p className="assist-material-error" role="alert">{materialError}</p>}
            <div className="assist-composer-row">
              <AssistantAddMenu disabled={chatting || readingFiles}
                planMode={assistantMode === 'plan'} onPlanMode={() => changeMode(modeRef.current === 'plan' ? 'standard' : 'plan')}
                onFiles={() => fileInputRef.current?.click()} onFolder={() => folderInputRef.current?.click()}
                onPage={() => {
                  const main = document.querySelector('main')
                  const raw = `页面：${pageName}\n路径：${here}\n${main?.innerText ?? ''}`.trim()
                  try {
                    updateMaterials(mergeMaterials(materialsRef.current, [{
                      id: `page:${here}`, name: `当前页 · ${pageName}`, text: raw.slice(0, 6000), truncated: raw.length > 6000, original_chars: raw.length,
                    }]))
                    setMaterialError('')
                  } catch (error) { setMaterialError(error instanceof Error ? error.message : '无法附加页面') }
                }} />
              <textarea
                aria-label="消息"
                ref={composerRef}
                rows={1}
                value={draft}
                placeholder={chatting ? subjectRunningRef.current ? '科目操作进行中，可点击停止' : '补充要求或调整方向…' : assistantMode === 'plan' ? '描述问题，先一起梳理方案…' : '问问题，或告诉我你想做什么…'}
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
                disabled={readingFiles || (!chatting && !draft.trim())}
                onClick={() => (chatting && !draft.trim() ? stopTurn() : send())}
                aria-label={chatting && !draft.trim() ? '停止' : '发送'}
                title={chatting && !draft.trim() ? '停止' : '发送'}
              >
                {chatting && !draft.trim() ? <i className="assist-send-dot" /> : <Icon name="send" size={13} />}
              </button>
            </div>
          </div>
          <p className="assist-here">{chatting ? subjectRunningRef.current ? '正在操作 · 可停止' : '处理中 · 可补充要求' : 'Enter 发送 · Shift + Enter 换行'}</p>
          {recoverable && (
            <button
              type="button"
              className="assist-recover-button"
              onClick={() => activeRunRef.current && void runLoop(activeRunRef.current)}
            >
              恢复查看上次任务
            </button>
          )}
        </section>
      )}
    </>
  )
}
