import { App, Button, Modal, Space, Tag } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { schedulingApi } from '@/api'
import type {
  Grade,
  SchedulingRuleDefinition,
  SchedulingRuleEvaluationResult,
  SchedulingRuleGroup,
} from '@/types'
import {
  isOrphanTeacherGapFreeRule,
  purgeOrphanTeacherGapFreeGroups,
  ruleGroupScopeLabel,
} from './RuleGroupWorkbench'

interface ScheduleVerifyWorkbenchProps {
  open: boolean
  onClose: () => void
  academicYear: string
  term: string
  classId?: number
  grades: Grade[]
  classes: Array<{ id: number; name: string; grade_id: number }>
}

type Mark = 'idle' | 'pass' | 'fail' | 'skip'

const statusMark = (result?: SchedulingRuleEvaluationResult): Mark => {
  if (!result) return 'idle'
  if (result.status === 'pass' || result.status === 'manual') return 'pass'
  if (result.status === 'fail' || result.status === 'unresolved' || result.status === 'not_run') {
    return 'fail'
  }
  return 'idle'
}

const markIcon = (mark: Mark) => {
  if (mark === 'pass') return '✓'
  if (mark === 'fail') return '✗'
  return '·'
}

export default function ScheduleVerifyWorkbench({
  open,
  onClose,
  academicYear,
  term,
  classId,
  grades,
  classes,
}: ScheduleVerifyWorkbenchProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [groups, setGroups] = useState<SchedulingRuleGroup[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<string>()
  const [selectedRuleId, setSelectedRuleId] = useState<string>()
  const [resultByRuleId, setResultByRuleId] = useState<
    Record<string, SchedulingRuleEvaluationResult>
  >({})
  const [verified, setVerified] = useState(false)
  const [meta, setMeta] = useState<{
    class_count: number
    schedule_item_count: number
    hard_failure_count: number
    soft_failure_count: number
    score: number
  } | null>(null)

  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true)
    setVerified(false)
    setResultByRuleId({})
    setMeta(null)
    setSelectedRuleId(undefined)
    schedulingApi
      .ruleGroups({ academic_year: academicYear, term })
      .then(async (catalog) => {
        if (!active) return
        let next = catalog.groups || []
        if (next.some((group) => group.rules?.some(isOrphanTeacherGapFreeRule))) {
          try {
            const cleaned = await purgeOrphanTeacherGapFreeGroups(next)
            const cleanedById = new Map(cleaned.map((item) => [item.id, item]))
            next = next.map(
              (group) =>
                cleanedById.get(group.id) || {
                  ...group,
                  rules: (group.rules || []).filter(
                    (rule) => !isOrphanTeacherGapFreeRule(rule),
                  ),
                },
            )
          } catch {
            next = next.map((group) => ({
              ...group,
              rules: (group.rules || []).filter(
                (rule) => !isOrphanTeacherGapFreeRule(rule),
              ),
            }))
          }
        }
        if (!active) return
        setGroups(next)
        const classGradeId = classId
          ? classes.find((item) => item.id === classId)?.grade_id
          : undefined
        const byGrade =
          classGradeId != null
            ? next.find((item) => Number(item.grade_id) === Number(classGradeId))
            : undefined
        const byActive = catalog.active_id
          ? next.find((item) => item.id === catalog.active_id)
          : undefined
        setSelectedGroupId(byGrade?.id || byActive?.id || next[0]?.id)
      })
      .catch((error) => {
        if (!active) return
        message.error(error instanceof Error ? error.message : '加载综合规则失败')
        setGroups([])
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [open, academicYear, term, classId, classes, message])

  const selectedGroup = useMemo(
    () => groups.find((item) => item.id === selectedGroupId),
    [groups, selectedGroupId],
  )

  const rules = useMemo(() => {
    const list = selectedGroup?.rules || []
    return list.filter((rule) => rule.enabled !== false)
  }, [selectedGroup])

  useEffect(() => {
    if (!selectedGroupId) {
      setSelectedRuleId(undefined)
      return
    }
    setVerified(false)
    setResultByRuleId({})
    setMeta(null)
    const first = (selectedGroup?.rules || []).find((rule) => rule.enabled !== false)
    setSelectedRuleId(first?.id)
  }, [selectedGroupId, selectedGroup])

  const selectedRule = rules.find((item) => item.id === selectedRuleId) || rules[0]
  const selectedResult = selectedRule ? resultByRuleId[selectedRule.id] : undefined

  const runVerify = async () => {
    if (!selectedGroupId) {
      message.warning('请先选择综合规则')
      return
    }
    setVerifying(true)
    try {
      const data = await schedulingApi.verifySchedule({
        academic_year: academicYear,
        term,
        class_id: classId,
        rule_group_id: selectedGroupId,
      })
      const map: Record<string, SchedulingRuleEvaluationResult> = {}
      for (const item of data.validation.results || []) {
        map[item.rule_id] = item
      }
      setResultByRuleId(map)
      setVerified(true)
      setMeta({
        class_count: data.class_count,
        schedule_item_count: data.validation.schedule_item_count,
        hard_failure_count: data.hard_failure_count,
        soft_failure_count: data.soft_failure_count,
        score: data.validation.score,
      })
      if (data.hard_failure_count === 0 && data.soft_failure_count === 0) {
        message.success('全部规则校验通过')
      } else if (data.hard_failure_count > 0) {
        message.warning(`硬约束未通过 ${data.hard_failure_count} 条`)
      } else {
        message.info(`软目标未达标 ${data.soft_failure_count} 条`)
      }
      const firstFail = (data.validation.results || []).find(
        (item) =>
          item.status === 'fail' ||
          item.status === 'unresolved' ||
          item.status === 'not_run',
      )
      if (firstFail) setSelectedRuleId(firstFail.rule_id)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '校验失败')
    } finally {
      setVerifying(false)
    }
  }

  const ruleMark = (rule: SchedulingRuleDefinition): Mark => {
    if (!verified) return 'idle'
    return statusMark(resultByRuleId[rule.id])
  }

  return (
    <Modal
      className="sk-verify-workbench-modal"
      title={
        <div>
          <span className="rule-group-eyebrow">VERIFY</span>
          <strong>结果反向校验工作台</strong>
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width="calc(100vw - 48px)"
      style={{ maxWidth: 1200 }}
      centered
      destroyOnClose
    >
      <div className="sk-verify-workbench">
        <aside className="sk-verify-sidebar">
          <div className="rule-group-sidebar-head">
            <span>RULE SET</span>
            <strong>选择综合规则</strong>
          </div>
          {loading ? (
            <p className="sk-verify-empty">正在加载规则…</p>
          ) : groups.length === 0 ? (
            <p className="sk-verify-empty">暂无综合规则，请先在「建立规则」中配置。</p>
          ) : (
            <div className="sk-verify-group-list">
              {groups.map((group) => {
                const scope = ruleGroupScopeLabel(
                  {
                    grade_id: group.grade_id != null ? Number(group.grade_id) : null,
                    scope: '',
                  },
                  grades,
                  classes,
                )
                return (
                  <button
                    key={group.id}
                    type="button"
                    className={group.id === selectedGroupId ? 'is-active' : ''}
                    onClick={() => setSelectedGroupId(group.id)}
                  >
                    <strong>{group.name}</strong>
                    <span>{scope}</span>
                    <em>{(group.rules || []).filter((r) => r.enabled !== false).length} 条</em>
                  </button>
                )
              })}
            </div>
          )}
        </aside>

        <section className="sk-verify-main">
          <div className="sk-verify-main-head">
            <div>
              <h3>{selectedGroup?.name || '请选择综合规则'}</h3>
              <p>
                {selectedGroup
                  ? `将用已保存课表逐条验算下列 ${rules.length} 条启用规则`
                  : '先在左侧选择要校验的综合规则'}
              </p>
            </div>
            <Space>
              {meta ? (
                <>
                  <Tag color={meta.hard_failure_count ? 'error' : 'success'}>
                    硬约束 ✗ {meta.hard_failure_count}
                  </Tag>
                  <Tag color={meta.soft_failure_count ? 'warning' : 'default'}>
                    软目标 ✗ {meta.soft_failure_count}
                  </Tag>
                  <Tag>
                    {meta.schedule_item_count} 节 · {meta.class_count} 班
                  </Tag>
                </>
              ) : null}
              <Button
                type="primary"
                loading={verifying}
                disabled={!selectedGroupId || loading}
                onClick={() => void runVerify()}
              >
                {verified ? '重新校验' : '开始校验'}
              </Button>
            </Space>
          </div>

          {!selectedGroup ? (
            <div className="sk-verify-empty-panel">请选择左侧综合规则</div>
          ) : rules.length === 0 ? (
            <div className="sk-verify-empty-panel">该综合规则下没有启用的细则</div>
          ) : (
            <div className="sk-verify-body">
              <div className="sk-verify-rule-list">
                {rules.map((rule) => {
                  const mark = ruleMark(rule)
                  return (
                    <button
                      key={rule.id}
                      type="button"
                      className={[
                        'sk-verify-rule-card',
                        rule.id === selectedRule?.id ? 'is-selected' : '',
                        mark === 'pass' ? 'is-pass' : '',
                        mark === 'fail' ? 'is-fail' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      onClick={() => setSelectedRuleId(rule.id)}
                    >
                      <i className={`sk-verify-mark is-${mark}`} aria-hidden="true">
                        {markIcon(mark)}
                      </i>
                      <div>
                        <strong>
                          {rule.id} · {rule.title}
                        </strong>
                        <span>
                          {rule.priority === 'hard' ? '硬约束' : '软目标'} · {rule.code}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
              <aside className="sk-verify-detail">
                {selectedRule ? (
                  <>
                    <div className="rule-group-sidebar-head">
                      <span>DETAIL</span>
                      <strong>{selectedRule.id}</strong>
                    </div>
                    <h4>{selectedRule.title}</h4>
                    <div className="sk-verify-detail-tags">
                      <Tag color={selectedRule.priority === 'hard' ? 'gold' : 'default'}>
                        {selectedRule.priority === 'hard' ? '硬约束' : '软目标'}
                      </Tag>
                      {verified ? (
                        <Tag
                          color={
                            statusMark(selectedResult) === 'pass' ? 'success' : 'error'
                          }
                        >
                          {statusMark(selectedResult) === 'pass' ? '通过 ✓' : '未通过 ✗'}
                        </Tag>
                      ) : (
                        <Tag>待校验</Tag>
                      )}
                    </div>
                    <p>
                      {verified
                        ? selectedResult?.message || '无详细说明'
                        : '点击右上角「开始校验」后，这里会显示该规则的验算说明。'}
                    </p>
                    {selectedResult && selectedResult.violation_count > 0 ? (
                      <small>
                        违规 {selectedResult.violation_count} 次
                        {selectedResult.penalty
                          ? ` · 罚分 ${selectedResult.penalty}`
                          : ''}
                      </small>
                    ) : null}
                  </>
                ) : (
                  <p className="sk-verify-empty">选择一条规则查看说明</p>
                )}
              </aside>
            </div>
          )}
        </section>
      </div>
    </Modal>
  )
}
