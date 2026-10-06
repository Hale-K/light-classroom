export type SubjectDraft = {
  name: string | null
  course_type: 'subject' | 'activity' | null
  evening_study_allowed: boolean | null
}

export function isSubjectCreationRequest(content: string): boolean {
  return /(?:新增|创建|添加|新建|增加).*(?:科目|学科)|(?:科目|学科).*(?:新增|创建|添加|新建)|生成(?:一个|一门|新的|新)?(?:科目|学科)/.test(content)
    || (/科目名称\s*[:：]/.test(content) && /(?:科目|课程)类型\s*[:：]/.test(content))
}

// This only identifies an action-shaped message. The model determines its intent.
export function mayRequestPageAction(content: string): boolean {
  return /(?:帮我|请|想|要|给我|能否|可以).{0,16}(?:新建|新增|创建|添加|安排|配置|设置|修改|删除|生成|建立|建一个|建一门|开一门)/.test(content)
    || /(?:新建|新增|创建|添加|安排|配置|设置|修改|删除|生成|建立|建一个|建一门|开一门).{0,24}(?:课程|课|科目|规则|排课|老师|班级|教室|学生|页面)/.test(content)
}

export function readExplicitSubjectName(content: string): string | null {
  const match = content.match(/(?:科目名称|名称|名字)\s*(?:是|叫|为|[:：])\s*[“「"']([^”」"']+)[”」"']/)
  if (match?.[1]?.trim()) return match[1].trim()
  const naturalName = content.match(/(?:新建|新增|创建|添加|建立|开)(?:一个|一门)?(?:校本)?(.+?)(?:的)?(?:专业课|课程|科目|学科)(?=[，,。；;\s]|$)/)
  return naturalName?.[1]?.trim() || null
}

export function isSubjectChoiceReply(content: string): boolean {
  return /^(?:(?:课程|科目)类型(?:是|为|[:：])?\s*)?(?:学科课|活动课)[\s，,。]*(?:(?:不允许|允许)(?:参加)?晚自习[。！!\s]*)?$/.test(content.trim())
}

export function readPendingSubjectDraft(raw: string | null): SubjectDraft | null {
  try {
    const value = JSON.parse(raw || 'null')
    if (!value || (value.name !== null && typeof value.name !== 'string')
      || (value.course_type !== null && !['subject', 'activity'].includes(value.course_type))
      || (value.evening_study_allowed !== null && typeof value.evening_study_allowed !== 'boolean')) return null
    return { name: value.name, course_type: value.course_type, evening_study_allowed: value.evening_study_allowed }
  } catch { return null }
}

export function isSubjectTaskCancellation(content: string): boolean {
  return /^(?:取消|停止|算了|不创建了|不用了)[。！!\s]*$/.test(content.trim())
}

// The subject page still submits through its normal API, with an additional
// exact-data guard while the agent owns the form.
let activeDraft: SubjectDraft | null = null

export function setActiveSubjectDraft(draft: SubjectDraft | null) {
  activeDraft = draft
  return () => { if (activeDraft === draft) activeDraft = null }
}

export function assertSubjectTaskSubmission(values: SubjectDraft, editing: boolean) {
  if (!activeDraft) return
  if (!activeDraft.course_type || activeDraft.evening_study_allowed === null
    || editing || values.name?.trim() !== activeDraft.name
    || values.course_type !== activeDraft.course_type
    || values.evening_study_allowed !== activeDraft.evening_study_allowed) {
    throw new Error('表单内容与已校验的科目数据不一致，已阻止保存。')
  }
}
