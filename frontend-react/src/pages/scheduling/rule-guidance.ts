import type { SchedulingRuleCode } from '../../types/index.ts'

interface RuleGuide { example: string; tip: string; recommended?: 'soft' }
export const RULE_GUIDANCE: Partial<Record<SchedulingRuleCode, RuleGuide>> = {
  slot_forbidden: { example: '教研会期间，周三第 5、6 节不安排数学课。', tip: '所选星期 × 节次共同生效。班级或全年级禁排会让这些课位保持空白。' },
  subject_allowed_slots: { example: '数学尽量安排在第 1～4 节，音乐尽量安排在第 8、9 节；也可改为必须满足。', tip: '同一入口表达学科能排在哪里：必须满足时只能排在所选课位；尽量满足时可设置允许例外数。它不会增加课时，周课时仍在课时管理中设置。', recommended: 'soft' },
  teacher_forbidden_slots: { example: '王老师周二上午不排课，其他时间正常安排。', tip: '老师在不同日期不可上课的节次不同时，使用“按具体课位”逐日设置。' },
  teacher_daily_limit: { example: '数学老师每天最多 4 节，需要时再开启白天不空节。', tip: '每日上限与白天连续性是不同要求；不空节需单独勾选，避免无意中增加限制。' },
  teacher_consecutive: { example: '李老师每周至少 2 天连续上 2 节，可选择同班或跨班。', tip: '至少天数不能超过所选星期数；连续长度需符合学校白天课位结构。' },
  teacher_preferred_weekdays: { example: '张老师的晚课优先安排在周一、周四。', tip: '本规则作用于晚课。偏好通常选“尽量满足”，避免过度限制可排日期。', recommended: 'soft' },
  teacher_multi_class_evening_adjacent: { example: '教两个班的老师，两个班的晚课优先相邻安排。', tip: '适用于有多个任教班级的老师；晚课课位需要先在课位结构中启用。', recommended: 'soft' },
  teacher_evening_daytime_link: { example: '有晚课的当天，同一老师还需在白天第 7 节授课。', tip: '只触发有晚课的日期；指定白天节次必须存在，需给教师保留足够可用课位。' },
  teacher_period_minimum: { example: '王老师在第 3、4、5 节中，每周合计至少安排 2 节。', tip: '下限按一周合计，不要求同一天；不应超过教师的周任教课时。' },
  subject_consecutive: { example: '物理实验课每周至少 1 天连续安排 2 节。', tip: '对每个班的每门所选学科分别要求连堂；周课时要足够支持连堂。' },
  class_slot_pattern: { example: '体育在周二上午和周四下午，或周二下午和周四上午。', tip: '选择 2 个星期，分别设置上午和下午节次；算法采用两种交叉方案之一。' },
  class_allowed_subjects: { example: '高一（1）班周五第 8 节只能安排音乐或美术。', tip: '限制这些课位可排的科目，不要求每个课位都有课，也不改变科目周课时。' },
  subject_prefer_early_periods: { example: '数学尽量安排在第 1～4 节，音乐尽量安排在第 8、9 节。', tip: '选择科目、节次和例外数即可；例外数按每班每科每周计算。', recommended: 'soft' },
  subject_gap_fill_late_periods: { example: '历史规则：音乐、美术优先第 8、9 节；后段已满或禁排时，可排前段。', tip: '仅供兼容已保存的旧配置；新增学科时间要求请使用“学科时间安排”，按对象、节次、例外数和满足程度表达。', recommended: 'soft' },
  class_evening_self_study_day: { example: '每班从周三、周四、周五中选 1 天，第 8、9 节留作自习。', tip: '这是白天第 8、9 节的自习日，不是晚自习；不同班可选择不同日期。' },
  class_gap_free: { example: '周一到周五，每班第 1～7 节都安排课程。', tip: '必须有足够周课时填满课位。班级禁排与“无空堂”可能矛盾，保存后仍需生成检查。' },
  student_contiguous: { example: '每名学生的公共课与走班课合并后，在所选节次不留空档。', tip: '固定为必须满足，使用公共课和走班课合并判断；可允许自习补空。' },
  student_gap_minimize: { example: '尽量把学生的公共课和走班课安排紧凑，减少等待。', tip: '固定为尽量满足，允许保留空档；适合先生成可行课表，再优化学生体验。', recommended: 'soft' },
  slot_teacher_balance: { example: '第 7 节尽量分摊给不同老师，每人每周最多 2 节。', tip: '按指定节次统计教师周课节数；教师人数较少时，可放宽上限或改为尽量满足。' },
  subject_evening_parity_pair: { example: '化学和生物在同一个晚课课位，单双周轮换。', tip: '选择 2 门学科，先核对它们的单双周课时与晚课资格。' },
  subject_daytime_parity_pair: { example: '单周化学、生物，与双周历史、地理在相同白天课位轮换。', tip: '单周组与双周组不能重叠，组内配对由算法决定；在课时管理中核对周期课时。' },
  slot_teacher_role_required: { example: '每班周五第 7 节都由本班班主任授课。', tip: '先在班级管理中配置班主任，并为该教师配置对应科目的任教关系。' },
}
