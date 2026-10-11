import { useState } from 'react'
import type { AssistantClarification } from '@/api/ai'
import './assistant-clarification.css'

export function restoreClarification(value: unknown): AssistantClarification | undefined {
  if (!value || typeof value !== 'object') return undefined
  const card = value as AssistantClarification
  if (typeof card.title !== 'string' || card.title.length > 160 || typeof card.next_step !== 'string' || card.next_step.length > 300
    || !Array.isArray(card.known_conditions) || card.known_conditions.length > 8 || card.known_conditions.some(v => typeof v !== 'string' || v.length > 500)
    || !Array.isArray(card.questions) || !card.questions.length || card.questions.length > 4) return undefined
  if (card.questions.some(q => !q || typeof q.id !== 'string' || !/^[a-zA-Z0-9_]{1,40}$/.test(q.id)
    || typeof q.title !== 'string' || !q.title.trim() || q.title.length > 160 || !Array.isArray(q.options) || q.options.length < 2 || q.options.length > 5
    || q.options.some(v => typeof v !== 'string' || !v.trim() || v.length > 120) || new Set(q.options).size !== q.options.length)
    || new Set(card.questions.map(q => q.id)).size !== card.questions.length) return undefined
  return card
}

export default function AssistantClarificationCard({ card, disabled, onSubmit }: {
  card: AssistantClarification; disabled: boolean; onSubmit: (answer: string) => void
}) {
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [custom, setCustom] = useState<Record<string, string>>({})
  const [review, setReview] = useState(false)
  const q = card.questions[step]
  const answer = answers[q.id] === '__custom' ? (custom[q.id] || '').trim() : answers[q.id]
  const value = (id: string) => answers[id] === '__custom' ? (custom[id] || '').trim() : answers[id]
  function submit() {
    if (card.questions.some(item => !value(item.id))) return
    onSubmit('继续之前的任务，保留已明确的条件。\n' + card.questions.map(item => `${item.title}：${value(item.id)}`).join('\n'))
  }
  return <section className="assist-clarify" aria-label="补充任务信息">
    <header><strong>{review ? '核对补充信息' : card.title}</strong><span aria-live="polite">{review ? '待提交' : `${step + 1} / ${card.questions.length}`}</span></header>
    {card.known_conditions.length > 0 && <details className="assist-clarify-known"><summary>已保留你的条件（点击查看）</summary><ul>{card.known_conditions.map((item, i) => <li key={i}>{item}</li>)}</ul></details>}
    {review ? <>
      <dl>{card.questions.map(item => <div key={item.id}><dt>{item.title}</dt><dd>{value(item.id)}</dd></div>)}</dl>
      <p>“暂不确定”的信息仍待确认。提交补充信息后继续分析。</p>
      <footer><button type="button" disabled={disabled} onClick={() => setReview(false)}>返回修改</button><button type="button" className="is-primary" disabled={disabled} onClick={submit}>提交并继续</button></footer>
    </> : <>
      <fieldset disabled={disabled}><legend>{q.title}</legend>
        {q.options.map((option, i) => <label className={answers[q.id] === option ? 'is-selected' : ''} key={option}>
          <input type="radio" aria-label={option} name={q.id} checked={answers[q.id] === option} onChange={() => setAnswers({ ...answers, [q.id]: option })} />
          <span className="assist-clarify-number">{i + 1}</span><span>{option}</span>
        </label>)}
        <label className={answers[q.id] === '__custom' ? 'is-selected' : ''}><input type="radio" name={q.id} checked={answers[q.id] === '__custom'} onChange={() => setAnswers({ ...answers, [q.id]: '__custom' })} /><span>其他补充</span></label>
        {answers[q.id] === '__custom' && <textarea aria-label="其他补充内容" maxLength={1000} placeholder="填写你的具体需求…" value={custom[q.id] || ''} onChange={e => setCustom({ ...custom, [q.id]: e.target.value })} />}
        <label className={answers[q.id] === '暂不确定' ? 'is-selected' : ''}><input type="radio" name={q.id} checked={answers[q.id] === '暂不确定'} onChange={() => setAnswers({ ...answers, [q.id]: '暂不确定' })} /><span>暂不确定</span></label>
      </fieldset>
      <p>下一步：{card.next_step}</p>
      <footer><button type="button" disabled={disabled || step === 0} onClick={() => setStep(step - 1)}>上一题</button>
        <button type="button" className="is-primary" disabled={disabled || !answer} onClick={() => step === card.questions.length - 1 ? setReview(true) : setStep(step + 1)}>{step === card.questions.length - 1 ? '核对答案' : '下一题'}</button></footer>
    </>}
  </section>
}
