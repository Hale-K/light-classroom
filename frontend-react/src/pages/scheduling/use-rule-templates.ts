import { useEffect, useMemo, useState } from 'react'
import { App } from 'antd'
import { schedulingApi } from '@/api'
import type { ScheduleRuleConfig, ScheduleRuleTemplate, TeacherScopeRule } from '@/types'
import {
  DEFAULT_RULE_TEMPLATE_KEY,
  RULE_TEMPLATES_KEY,
  cloneRuleConfig,
  keepSingleEnabledTemplate,
  loadRuleTemplates,
} from './scheduling-model'

export interface RuleTemplateForm {
  name: string
  desc: string
  config: ScheduleRuleConfig
  scope_rules: TeacherScopeRule[]
}

interface Options {
  academicYear: string
  term: string
  onConfigApplied: (config: ScheduleRuleConfig) => void
  onScopeRulesApplied: (rules: TeacherScopeRule[]) => void
}

function cloneScopeRules(rules: TeacherScopeRule[] | undefined): TeacherScopeRule[] {
  return JSON.parse(JSON.stringify(rules || [])) as TeacherScopeRule[]
}

export default function useRuleTemplates({
  academicYear,
  term,
  onConfigApplied,
  onScopeRulesApplied,
}: Options) {
  const { message } = App.useApp()
  const [ruleTemplates, setRuleTemplates] = useState<ScheduleRuleTemplate[]>(() => {
    const loaded = loadRuleTemplates()
    const defaultId = localStorage.getItem(DEFAULT_RULE_TEMPLATE_KEY) || 'builtin-balanced'
    return keepSingleEnabledTemplate(loaded, defaultId)
  })
  const [defaultRuleTemplateId, setDefaultRuleTemplateId] = useState(
    () => localStorage.getItem(DEFAULT_RULE_TEMPLATE_KEY) || 'builtin-balanced',
  )
  const [ruleTemplateModalOpen, setRuleTemplateModalOpen] = useState(false)
  const [editingRuleTemplateId, setEditingRuleTemplateId] = useState<string>()
  const [ruleTemplateForm, setRuleTemplateForm] = useState<RuleTemplateForm>({
    name: '',
    desc: '',
    config: cloneRuleConfig(),
    scope_rules: [],
  })

  const persistRuleTemplates = (next: ScheduleRuleTemplate[]) => {
    setRuleTemplates(next)
    try { localStorage.setItem(RULE_TEMPLATES_KEY, JSON.stringify(next)) } catch {}
  }

  useEffect(() => {
    if (!ruleTemplates.some((template) => template.id === defaultRuleTemplateId)) {
      const firstEnabled = ruleTemplates.find((template) => template.enabled !== false)
      if (firstEnabled) setDefaultRuleTemplateId(firstEnabled.id)
    }
    // 默认模板只在首次挂载时纠正一次，避免模板编辑触发额外切换。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    try { localStorage.setItem(DEFAULT_RULE_TEMPLATE_KEY, defaultRuleTemplateId) } catch {}
  }, [defaultRuleTemplateId])

  const activeRuleTemplate = useMemo(
    () => ruleTemplates.find((template) => template.enabled !== false),
    [ruleTemplates],
  )

  const applyRuleTemplate = async (template: ScheduleRuleTemplate) => {
    onConfigApplied(cloneRuleConfig(template.config))
    const scopeRules = cloneScopeRules(template.scope_rules)
    onScopeRulesApplied(scopeRules)
    try {
      await schedulingApi.saveScopeRules({ academic_year: academicYear, term, rules: scopeRules })
    } catch {
      // 模板切换的本地状态仍然有效，后端同步失败不阻断页面操作。
    }
  }

  const openRuleTemplateModal = (template?: ScheduleRuleTemplate) => {
    setEditingRuleTemplateId(template?.id)
    setRuleTemplateForm(template
      ? {
          name: template.name,
          desc: template.desc || '',
          config: cloneRuleConfig(template.config),
          scope_rules: cloneScopeRules(template.scope_rules),
        }
      : {
          name: '',
          desc: '',
          config: cloneRuleConfig(),
          scope_rules: [],
        })
    setRuleTemplateModalOpen(true)
  }

  const saveRuleTemplate = () => {
    const name = ruleTemplateForm.name.trim()
    if (!name) {
      message.warning('请填写规则模板名称')
      return
    }

    const scopeRules = ruleTemplateForm.scope_rules.length > 0
      ? cloneScopeRules(ruleTemplateForm.scope_rules)
      : undefined
    const timestamp = new Date().toISOString()

    if (editingRuleTemplateId) {
      persistRuleTemplates(ruleTemplates.map((template) => template.id === editingRuleTemplateId
        ? { ...template, name, desc: ruleTemplateForm.desc, config: ruleTemplateForm.config, scope_rules: scopeRules, updated_at: timestamp }
        : template))
      message.success('规则模板已更新')
    } else {
      persistRuleTemplates([
        ...ruleTemplates,
        {
          id: `tpl_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          name,
          desc: ruleTemplateForm.desc,
          config: ruleTemplateForm.config,
          scope_rules: scopeRules,
          created_at: timestamp,
          updated_at: timestamp,
        },
      ])
      message.success('规则模板已创建')
    }
    setRuleTemplateModalOpen(false)
  }

  const deleteRuleTemplate = (template: ScheduleRuleTemplate) => {
    if (template.id.startsWith('builtin-')) {
      message.warning('内置规则模板不可删除')
      return
    }
    const next = ruleTemplates.filter((item) => item.id !== template.id)
    persistRuleTemplates(next)
    if (defaultRuleTemplateId === template.id) setDefaultRuleTemplateId(next[0]?.id || '')
    message.success('规则模板已删除')
  }

  const toggleRuleTemplate = (template: ScheduleRuleTemplate) => {
    const turningOn = template.enabled === false
    const timestamp = new Date().toISOString()
    const next = turningOn
      ? ruleTemplates.map((item) => item.id === template.id
          ? { ...item, enabled: true, updated_at: timestamp }
          : { ...item, enabled: false })
      : ruleTemplates.map((item) => item.id === template.id
          ? { ...item, enabled: false, updated_at: timestamp }
          : item)

    if (turningOn) {
      setDefaultRuleTemplateId(template.id)
      void applyRuleTemplate(template)
    } else if (defaultRuleTemplateId === template.id) {
      setDefaultRuleTemplateId('')
    }
    persistRuleTemplates(next)
    message.success(turningOn ? `规则「${template.name}」已启用` : `规则「${template.name}」已停用`)
  }

  return {
    ruleTemplates,
    defaultRuleTemplateId,
    setDefaultRuleTemplateId,
    ruleTemplateModalOpen,
    setRuleTemplateModalOpen,
    editingRuleTemplateId,
    ruleTemplateForm,
    setRuleTemplateForm,
    activeRuleTemplate,
    persistRuleTemplates,
    applyRuleTemplate,
    openRuleTemplateModal,
    saveRuleTemplate,
    deleteRuleTemplate,
    toggleRuleTemplate,
  }
}
