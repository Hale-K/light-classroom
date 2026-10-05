import type { SubjectDraft } from '../src/assistant/subjectTask'

export function validateFixture(content: string, previous: SubjectDraft | undefined, names: string[]) {
  const requestName = content.match(/(?:叫|名称[为是：:]?)\s*[“「]?([^”」。，,\s]+)/)?.[1]
  const choiceReply = /学科课|活动课|允许|晚自习/.test(content)
  const name = requestName || previous?.name || (!choiceReply && !/新增|创建|添加|生成/.test(content) ? content.trim() : null)
  const course_type = content.includes('活动课') ? 'activity' : content.includes('学科课') ? 'subject' : previous?.course_type ?? null
  const evening_study_allowed = content.includes('不允许') ? false : content.includes('允许') ? true : previous?.evening_study_allowed ?? null
  const draft: SubjectDraft = { name, course_type, evening_study_allowed }
  const missing = [!name || name.length > 20 ? '科目名称（1～20 个字）' : '',
    !course_type ? '课程类型：学科课还是活动课？' : '',
    evening_study_allowed === null ? '晚自习资格：允许还是不允许？' : ''].filter(Boolean)
  const status = missing.length ? 'needs_input' : names.includes(name!) ? 'exists' : 'ready'
  return { status, draft, text: status === 'needs_input' ? '还需要你明确提供：\n' + missing.map(field => `• ${field}`).join('\n') : status === 'exists' ? `「${name}」已存在，无需重复创建。` : '数据校验通过' }
}
