import { useRef, useState } from 'react'
import { assistantApi, type AssistantPlan } from '@/api'

export default function AssistantRulePlan({ plan, disabled, onChange }: {
  plan: AssistantPlan
  disabled: boolean
  onChange: (plan: AssistantPlan) => void
}) {
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [error, setError] = useState('')
  const expired = Date.parse(plan.expires_at) <= Date.now()
  const decide = async (decision: 'confirm' | 'cancel') => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setError('')
    try {
      const result = await assistantApi.decide(plan.id, decision)
      onChange(result)
      if (result.status === 'executed') window.dispatchEvent(new Event('lc-assistant-rules-saved'))
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作结果暂未收到，可重试核对；重复确认不会重复添加。')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }
  return (
    <section className="assist-rule-plan" aria-label="规则确认草稿" aria-busy={busy}>
      <strong>{plan.status === 'executed' ? '规则已保存' : plan.status === 'cancelled' ? '草稿已取消' : '待确认 · 规则草稿'}</strong>
      <p>{plan.summary}</p>
      {plan.status === 'pending' && <>
        <small>{expired ? '草稿已过期，请重新描述需求生成预览。' : '20 分钟内有效。请核对后保存；修改要求可直接继续对话。'}</small>
        <div className="assist-plan-actions">
          <button type="button" className="is-ok" disabled={disabled || busy || expired} onClick={() => void decide('confirm')}>{busy ? '正在处理…' : '确认保存规则'}</button>
          <button type="button" disabled={disabled || busy || expired} onClick={() => void decide('cancel')}>取消草稿</button>
        </div>
      </>}
      {plan.result && <p role="status">{plan.result.text}</p>}
      {plan.status === 'cancelled' && <small>未写入规则。</small>}
      {error && <p role="alert">{error} 如未收到回执，可重试核对，同一草稿不会重复添加。</p>}
    </section>
  )
}
