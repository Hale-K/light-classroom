import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { onboardingApi, type OnboardingStep } from '@/api'
import Icon from '@/components/Icon'
import './onboarding.css'

/** 新手引导页：教务排课准备流程，状态来自后端真实数据。 */
export default function OnboardingView() {
  const navigate = useNavigate()
  const [steps, setSteps] = useState<OnboardingStep[]>([])
  const [historyYear, setHistoryYear] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const refresh = useCallback(() => {
    onboardingApi.status()
      .then((data) => {
        setSteps(data.steps || [])
        setHistoryYear(data.history_year ?? null)
        setDismissed(Boolean(data.dismissed))
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const doneCount = steps.filter((s) => s.done).length
  const total = steps.length || 1
  const allDone = loaded && steps.length > 0 && doneCount === total
  const firstPending = steps.findIndex((s) => !s.done)
  const pending = steps.filter((s) => !s.done)
  const doneSteps = steps.filter((s) => s.done)

  const skip = () => {
    void onboardingApi.dismiss().catch(() => undefined)
    setDismissed(true)
    navigate('/scheduling')
  }

  const reopen = () => {
    void onboardingApi.reopen().catch(() => undefined)
    setDismissed(false)
  }

  const ringC = 2 * Math.PI * 34

  return (
    <div className="ob-page">
      <section className="ob-banner">
        <div className="ob-banner-copy">
          <h1>按步骤准备排课基础数据</h1>
          <p>核对学年学期，准备教师人员，建全空间并完成资源分配与班级划分，再配置课位、课时、任教和规则，最后生成课表。</p>
          <div className="ob-banner-tips">
            <span>✓ 建议按顺序完成</span>
            {historyYear && !allDone && (
              <span className="ob-history">检测到 {historyYear} 学年的历史数据，新学期沿用同样结构即可</span>
            )}
            {allDone && <span className="ob-history">基础记录已齐，请继续核对约束和生成结果</span>}
          </div>
          <div className="ob-banner-actions">
            <button type="button" onClick={refresh}>
              <Icon name="rotate" size={14} />刷新进度
            </button>
            {allDone ? (
              dismissed ? (
                <button type="button" className="is-ghost" onClick={reopen}>重新开启引导入口</button>
              ) : (
                <button type="button" className="is-ghost" onClick={skip}>不再显示引导</button>
              )
            ) : (
              <button type="button" className="is-ghost" onClick={skip} disabled={dismissed}>
                {dismissed ? '已跳过引导' : '已自有数据，跳过引导'}
              </button>
            )}
          </div>
        </div>
        <div className="ob-ring-wrap">
          <svg viewBox="0 0 84 84" className="ob-ring" role="img" aria-label={`进度 ${doneCount}/${total}`}>
            <circle className="ob-ring-bg" cx="42" cy="42" r="34" />
            <circle
              className="ob-ring-fg"
              cx="42"
              cy="42"
              r="34"
              strokeDasharray={`${(ringC * doneCount) / total} ${ringC}`}
              transform="rotate(-90 42 42)"
            />
          </svg>
          <div className="ob-ring-num">
            <strong>{loaded ? `${doneCount}/${total}` : '…'}</strong>
            <span>{allDone ? '已完成' : '进行中'}</span>
          </div>
        </div>
      </section>

      <section className="ob-cards">
        {pending.map((step) => {
          const order = steps.indexOf(step)
          const isNext = order === firstPending
          return (
            <article key={step.key} className={`ob-card${isNext ? ' is-next' : ''}`}>
              <span className="ob-card-icon"><Icon name="sparkles" size={20} /></span>
              <div className="ob-card-body">
                <header>
                  <em>{order + 1}</em>
                  <strong>{step.title}</strong>
                  {isNext && <i className="ob-badge">下一步</i>}
                </header>
                <p>{step.detail}</p>
              </div>
              <button type="button" className={isNext ? 'is-primary' : ''} onClick={() => navigate(step.path)}>
                去完成
              </button>
            </article>
          )
        })}
        {doneSteps.length > 0 && (
          <article className="ob-done-card">
            <header>已完成 {doneSteps.length} 步</header>
            <ul>
              {doneSteps.map((s) => (
                <li key={s.key}>
                  <i>✓</i>
                  <strong>{s.title}</strong>
                  <small>{s.detail}</small>
                </li>
              ))}
            </ul>
          </article>
        )}
        {loaded && steps.length === 0 && <p className="ob-empty">进度读取失败，请稍后点「刷新进度」重试。</p>}
      </section>
    </div>
  )
}
