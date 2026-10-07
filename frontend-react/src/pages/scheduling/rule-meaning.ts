export interface RuleMeaningInput {
  target: string
  operator: string
  time?: string
  requiredTeacherRole?: string
  detail?: string
  cycle?: string
}

const ACTION_LABELS: Record<string, string> = {
  禁止排课: '不排',
  禁止占用指定课位: '不排',
  仅允许指定课位: '仅排指定课位',
  仅允许指定科目: '仅排指定科目',
  固定到指定课位: '固定课位',
  必须安排: '必须安排',
  要求连堂: '连堂',
  保持连堂: '保持连堂',
  均衡分布: '均衡分布',
  每日课节上限: '每日限课',
  主科靠前: '尽量靠前',
  空节补活动课: '空节补课',
  优先安排: '优先安排',
  尽量避开: '尽量避开',
  保持连续: '保持连续',
  尽量连续: '尽量连续',
  均衡分配: '均衡分配',
  优先相邻安排: '优先相邻',
  晚课日固定节次: '晚课日固定节次',
  节次课时下限: '节次课时达下限',
  组合限制: '组合限制',
  单双周配对: '单双周配对',
  互斥排课: '互斥排课',
  保持相邻: '保持相邻',
  固定关联: '固定关联',
  选择自习日: '选择自习日',
}

export const conciseRuleMeaning = ({
  target,
  operator,
  time,
  requiredTeacherRole,
  detail,
  cycle,
}: RuleMeaningInput): string => {
  const subject = target.trim() || '未指定对象'
  const action = requiredTeacherRole === 'head_teacher' && operator === '必须安排'
    ? '班主任上课'
    : ACTION_LABELS[operator] || operator
  const parts = [action, time?.trim(), detail?.trim(), cycle && cycle !== '每周' ? cycle : '']
    .filter(Boolean)
  return `${subject}：${parts.join(' · ')}`
}
