import type { SchedulingRuleCode } from '../../types/index.ts';

export type RuleScope = '全局' | '课位' | '学科' | '教师' | '班级';
const scopesByFamily = {
  slot: ['全局', '课位', '学科', '教师', '班级'],
  distribution: ['学科', '班级', '教师'],
  teacher: ['教师'],
  class: ['班级'],
  combination: ['全局', '课位', '学科', '教师', '班级'],
} satisfies Record<string, RuleScope[]>;

export function scopeOptionsForRule(family: keyof typeof scopesByFamily, code: SchedulingRuleCode): RuleScope[] {
  if (code === 'class_gap_free') return ['全局', '班级'];
  if (code === 'student_gap_minimize' || code === 'student_contiguous') return ['全局'];
  if (code === 'teacher_daily_limit' || code === 'teacher_gap_free') return ['教师', '学科'];
  if (code === 'slot_forbidden') return ['学科', '教师', '班级', '全局'];
  if (code === 'subject_allowed_slots') return ['学科'];
  if (code === 'slot_teacher_role_required') return ['全局'];
  if (code === 'teacher_period_minimum') return ['教师'];
  if (code === 'subject_consecutive' || code === 'class_slot_pattern') return ['学科'];
  if (code === 'teacher_consecutive') return ['教师'];
  if (code === 'subject_daytime_parity_pair') return ['学科'];
  return scopesByFamily[family];
}
