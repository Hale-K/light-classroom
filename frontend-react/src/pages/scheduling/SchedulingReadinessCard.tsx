import { useCallback, useEffect, useState } from 'react'
import { Button, Progress, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { onboardingApi, type OnboardingStatus, type OnboardingStep } from '@/api'
import Icon from '@/components/Icon'

export default function SchedulingReadinessCard() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<OnboardingStatus>()
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setFailed(false)
    try {
      const result = await onboardingApi.status(signal)
      if (!result.steps?.length) throw new Error('未返回排课准备项')
      setStatus(result)
    } catch {
      if (!signal?.aborted) setFailed(true)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  if (!loading && status?.audience && status.audience !== 'management') return null

  const steps = status?.steps ?? []
  const requiredSteps = steps.filter((step) => step.required !== false)
  const optionalSteps = steps.filter((step) => step.required === false)
  const doneCount = requiredSteps.filter((step) => step.done).length
  const nextStep = requiredSteps.find((step) => !step.done)
  const percent = requiredSteps.length ? Math.round(doneCount * 100 / requiredSteps.length) : 0

  const openStep = (step: OnboardingStep) => navigate(step.path)

  return (
    <section className="sk-readiness" aria-labelledby="sk-readiness-title" aria-busy={loading}>
      <div className="sk-readiness-summary">
        <div className="sk-readiness-copy">
          <div className="sk-readiness-heading">
            <h3 id="sk-readiness-title">全校排课准备</h3>
            {loading ? <Tag>检查中</Tag> : !failed && <Tag color={nextStep ? 'processing' : 'success'}>
              {nextStep ? `${doneCount}/${requiredSteps.length} 项基础准备已完成` : '基础准备已齐'}
            </Tag>}
          </div>
          <p>
            {loading ? '正在检查全校排课基础数据…' : failed ? '暂时无法读取准备进度，请重试。' : nextStep
              ? `建议先完成「${nextStep.title}」：${nextStep.detail}`
              : '基础数据检查已完成；课时是否匹配、教师与教室是否冲突，还需在联合预览中验证。'}
          </p>
        </div>
        {!loading && !failed && requiredSteps.length > 0 && (
          <Progress className="sk-readiness-progress" percent={percent} size="small" />
        )}
        <div className="sk-readiness-actions">
          {failed ? <Button onClick={() => void refresh()}>重试</Button> : nextStep && (
            <Button type="primary" onClick={() => openStep(nextStep)}>去处理</Button>
          )}
          <Button aria-label="刷新排课准备情况" icon={<Icon name="rotate" size={14} />}
            disabled={loading} onClick={() => void refresh()} />
        </div>
      </div>

      {!loading && !failed && steps.length > 0 && (
        <details className="sk-readiness-details">
          <summary>查看全部准备项（{requiredSteps.length} 项必需{optionalSteps.length ? `，${optionalSteps.length} 项可选` : ''}）</summary>
          <ol>
            {requiredSteps.map((step) => (
              <li key={step.key} className={step.done ? 'is-done' : 'is-pending'}>
                <span className="sk-readiness-state" aria-label={step.done ? '已完成' : '待处理'}>
                  {step.done ? '✓' : '·'}
                </span>
                <div><strong>{step.title}</strong><p>{step.detail}</p></div>
                {!step.done && <Button type="link" onClick={() => openStep(step)}>去处理</Button>}
              </li>
            ))}
            {optionalSteps.map((step) => (
              <li key={step.key} className="is-optional">
                <Tag>可选</Tag>
                <div><strong>{step.title}</strong><p>{step.detail}</p></div>
                <Button type="link" onClick={() => openStep(step)}>查看</Button>
              </li>
            ))}
          </ol>
          <p className="sk-readiness-footnote">此清单只核对基础准备情况，不代表课表一定可排；联合预览会继续检查具体课时、资源冲突和排课条件。</p>
        </details>
      )}
    </section>
  )
}
