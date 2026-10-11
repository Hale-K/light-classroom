import type { RuleCheckIssue } from './rule-workbench-checks'

const labels = { duplicate: '重复配置', redundant: '职责覆盖', overlap: '范围交叉', conflict: '要求冲突', incomplete: '信息缺失' }

export function RuleCheckReport({ issues, links, onSelect }: {
  issues: RuleCheckIssue[]
  links: Record<string, { id: string; title: string }>
  onSelect: (id: string) => void
}) {
  const errors = issues.filter(i => i.level === 'error').length
  return <div className="rule-workbench-report" aria-live="polite">
    <strong>{issues.length ? `${errors} 项必须处理 · ${issues.length - errors} 项建议` : '暂未发现明显配置矛盾'}</strong>
    {issues.map((issue, index) => <div className={`rule-workbench-check-item is-${issue.level}`} key={`${issue.ruleIds.join('-')}-${index}`}>
      <b>{issue.kind ? labels[issue.kind] : issue.level === 'error' ? '需处理' : '建议'}{issue.level === 'error' ? ' · 阻止当前冲突规则保存' : ' · 可继续保存'}</b>
      {issue.context && <small className="rule-workbench-check-context">影响范围：{issue.context}</small>}
      <p>{issue.message}</p>
      {issue.suggestions?.length ? <><strong className="rule-workbench-remedy-title">可以这样化解</strong><ul>{issue.suggestions.map(s => <li key={s}>{s}</li>)}</ul></> : null}
      <div className="rule-workbench-related-rules">{[...new Set(issue.ruleIds.map(id => links[id]?.id).filter(Boolean))].map(id => {
        const linked = Object.values(links).find(link => link.id === id)!
        return <button key={id} type="button" onClick={() => onSelect(id)}>调整 {linked.id} · {linked.title}</button>
      })}</div>
    </div>)}
  </div>
}
