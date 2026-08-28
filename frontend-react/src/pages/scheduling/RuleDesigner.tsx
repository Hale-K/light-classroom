import { Button, Form, InputNumber, Modal, Select, Tag } from 'antd'
import type {
  ScheduleRuleConfig,
  ScheduleRuleSuggestion,
  ScheduleStrategyOption,
  ScheduleValidationIssue,
  ScheduleValidationResult,
} from '@/types'

interface RuleDesignerProps {
  open: boolean
  value: ScheduleRuleConfig
  strategies: ScheduleStrategyOption[]
  validation: ScheduleValidationResult | null
  validating: boolean
  issueText: (issue: ScheduleValidationIssue) => string
  onChange: (value: ScheduleRuleConfig) => void
  onValidate: () => void
  onClose: () => void
  readOnly?: boolean
  onConfirm?: () => void
}

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function RuleDesigner({
  open,
  value,
  strategies,
  validation,
  validating,
  issueText,
  onChange,
  onValidate,
  onClose,
  readOnly = false,
  onConfirm,
}: RuleDesignerProps) {
  const update = <K extends keyof ScheduleRuleConfig>(field: K, next: ScheduleRuleConfig[K]) => {
    onChange({ ...value, [field]: next })
  }

  const slotOptions = Array.from({ length: value.days }, (_, day) =>
    Array.from({ length: value.periods_per_day }, (_, period) => ({
      value: `${day + 1}-${period + 1}`,
      label: `${WEEKDAY_LABELS[day]} 第 ${period + 1} 节`,
    })),
  ).flat()

  const availableSlots = value.days * value.periods_per_day - value.forbidden_slots.length
  const activeSuggestion = (suggestion: ScheduleRuleSuggestion) =>
    suggestion.field !== 'weekly_periods' && suggestion.field in value

  const applySuggestion = (suggestion: ScheduleRuleSuggestion) => {
    if (!activeSuggestion(suggestion)) return
    onChange({
      ...value,
      [suggestion.field]: suggestion.recommended_value,
    })
  }

  return (
    <Modal
      title={<div className="sk-rule-modal-title"><span>排课规则设计器</span><Tag color={validation?.valid ? 'success' : validation ? 'warning' : 'default'}>
        {validation?.valid ? '校验通过' : validation ? '存在冲突' : '尚未校验'}
      </Tag></div>}
      open={open}
      onCancel={onClose}
      centered
      width={1120}
      zIndex={1100}
      className="sk-rule-modal"
      footer={
        <div className="sk-rule-footer">
          <span>{readOnly ? '请确认当前规则，确认后将直接生成课表。' : '修改规则后请重新校验。'}</span>
          <div>
            <Button onClick={onClose}>关闭</Button>
            {readOnly ? (
              <Button type="primary" onClick={onConfirm}>确认生成课表</Button>
            ) : (
              <Button type="primary" loading={validating} onClick={onValidate}>校验并保存规则</Button>
            )}
          </div>
        </div>
      }
    >
      <div className="sk-rule-layout">
        <div className="sk-rule-editor">
          <section className="sk-rule-section">
            <div className="sk-rule-title"><span>01</span><div><h3>时间结构</h3><p>定义一周有多少个可用于排课的时段。</p></div></div>
            <Form layout="vertical" className="sk-form-grid">
              <Form.Item label="每周教学日">
                <InputNumber disabled={readOnly} value={value.days} min={1} max={7} onChange={(next) => update('days', next ?? 5)} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="每日节数">
                <InputNumber disabled={readOnly} value={value.periods_per_day} min={1} max={12} onChange={(next) => update('periods_per_day', next ?? 7)} style={{ width: '100%' }} />
              </Form.Item>
            </Form>
            <div className="sk-rule-equation">
              <span>基础容量</span>
              <strong>{value.days} 天 × {value.periods_per_day} 节 − {value.forbidden_slots.length} 个禁排 = {availableSlots} 节</strong>
            </div>
          </section>

          <section className="sk-rule-section">
            <div className="sk-rule-title"><span>02</span><div><h3>负荷上限</h3><p>这些是硬约束，任何生成策略都不能突破。</p></div></div>
            <Form layout="vertical" className="sk-form-grid">
              <Form.Item label="班级每日最多课时">
                <InputNumber disabled={readOnly} value={value.max_class_lessons_per_day} min={1} max={value.periods_per_day} onChange={(next) => update('max_class_lessons_per_day', next ?? value.periods_per_day)} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="教师每日最多课时">
                <InputNumber disabled={readOnly} value={value.max_teacher_lessons_per_day} min={1} max={value.periods_per_day} onChange={(next) => update('max_teacher_lessons_per_day', next ?? value.periods_per_day)} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="教师每周最多课时">
                <InputNumber disabled={readOnly} value={value.max_teacher_weekly_periods ?? 30} min={1} max={60} onChange={(next) => update('max_teacher_weekly_periods', next ?? 30)} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="体育课每周节数">
                <InputNumber
                  disabled={readOnly}
                  value={value.pe_weekly_periods}
                  min={1}
                  max={6}
                  placeholder="默认 4"
                  onChange={(next) => update('pe_weekly_periods', next ?? undefined)}
                  style={{ width: '100%' }}
                />
              </Form.Item>
              <Form.Item label="同班同科每日最多课时">
                <InputNumber disabled={readOnly} value={value.max_same_subject_per_day} min={1} max={6} onChange={(next) => update('max_same_subject_per_day', next ?? 1)} style={{ width: '100%' }} />
              </Form.Item>
            </Form>
          </section>

          <section className="sk-rule-section">
            <div className="sk-rule-title"><span>03</span><div><h3>禁排时段</h3><p>适用于全校例会、教研活动或场地关闭。</p></div></div>
            <Select
              disabled={readOnly}
              mode="multiple"
              value={value.forbidden_slots}
              onChange={(next: string[]) => update('forbidden_slots', next)}
              options={slotOptions}
              optionFilterProp="label"
              placeholder="选择全校不可排课的时段"
              style={{ width: '100%' }}
            />
          </section>

          <section className="sk-rule-section">
            <div className="sk-rule-title"><span>04</span><div><h3>优化策略</h3><p>属于软约束，选择顺序就是算法比较优先级。</p></div></div>
            <Select
              disabled={readOnly}
              mode="multiple"
              value={value.strategy_codes}
              onChange={(next: string[]) => update('strategy_codes', next)}
              options={strategies.map((strategy) => ({
                value: strategy.code,
                label: strategy.name,
                title: strategy.description,
              }))}
              optionFilterProp="label"
              placeholder="至少选择一种策略"
              style={{ width: '100%' }}
            />
            <ol className="sk-strategy-order">
              {value.strategy_codes.map((code, index) => {
                const strategy = strategies.find((item) => item.code === code)
                return <li key={code}><b>{index + 1}</b><div><strong>{strategy?.name || code}</strong><span>{strategy?.description}</span></div></li>
              })}
            </ol>
          </section>
        </div>

        <aside className="sk-rule-audit" aria-live="polite">
          <div className="sk-rule-audit-head">
            <span>RULE AUDIT</span>
            <h3>{validation ? (validation.valid ? '规则可执行' : `${validation.issues.length} 项硬冲突`) : '等待校验'}</h3>
            <p>{validation ? `需要安排 ${validation.requested_lessons} 节课，基础时段池 ${validation.available_slots} 节。` : '点击“校验当前规则”，系统会用真实任教关系计算冲突。'}</p>
          </div>

          {validation?.rules?.map((rule) => (
            <div key={rule.code} className="sk-rule-proof">
              <span>{rule.label}</span>
              <strong>{rule.formula}</strong>
              <p>{rule.description}</p>
            </div>
          ))}

          {validation?.issues.map((issue) => (
            <div key={`${issue.code}-${issue.entity_id}-${issue.related_id || 0}`} className="sk-rule-conflict">
              <span>硬冲突 · {issue.rule_code}</span>
              <strong>{issueText(issue)}</strong>
              {issue.formula && <code>{issue.formula}</code>}
              {issue.suggestions?.map((suggestion) => (
                <div key={suggestion.code} className="sk-rule-suggestion">
                  <div><b>{suggestion.label}</b><p>{suggestion.reason}</p><small>{suggestion.tradeoff}</small></div>
                  {!readOnly && activeSuggestion(suggestion) && <Button size="small" onClick={() => applySuggestion(suggestion)}>采用</Button>}
                </div>
              ))}
            </div>
          ))}
        </aside>
      </div>
    </Modal>
  )
}
