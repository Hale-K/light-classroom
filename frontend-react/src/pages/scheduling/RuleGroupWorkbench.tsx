import {
  App,
  Button,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Tooltip,
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { schedulingApi } from "@/api";
import { setAssistantContext, clearAssistantContext } from '@/assistant/context';
import type {
  Grade,
  SchedulingGridConfig,
  SchedulingResources,
  SchedulingRuleCode,
  SchedulingRuleDefinition,
  SchedulingRuleGroup,
} from "@/types";
type RuleScope = "全局" | "课位" | "学科" | "教师" | "班级";
type RuleCategory = "global" | "subject" | "teacher" | "class" | "evening";
type RuleKind = "禁排" | "固定" | "偏好" | "连续" | "配对" | "课时";
type RulePriority = "hard" | "soft";
type RuleStatus = "pass" | "warning" | "unresolved";
type RuleFamily = "slot" | "distribution" | "teacher" | "class" | "combination";
type RuleTemplateId = Exclude<SchedulingRuleCode, "manual_review">;
type QuantityUnit =
  "period" | "section" | "per_class" | "per_day" | "unlimited";
type DistributionTarget =
  "none" | "consecutive" | "daily-limit" | "morning-afternoon";

interface SpecificSlot {
  weekday: number;
  periods: number[];
}

interface QuantitySpec {
  amount?: number;
  unit: QuantityUnit;
  distribution: string;
}

interface DistributionSpec {
  target: DistributionTarget;
  consecutiveLength?: number;
  minimumDays?: number;
  maxLessonsPerDay?: number;
  patternMode?: "either-direction";
  /** 上下午分布：参与对开的星期（通常 2 个） */
  patternWeekdays?: number[];
  /** 上午节次集合 */
  morningPeriods?: number[];
  /** 下午节次集合 */
  afternoonPeriods?: number[];
  /** 教师连堂：同班连堂或跨班连堂 */
  teacherClassMode?: "same_class" | "cross_class";
}

const RULE_FAMILY_LABELS: Record<RuleFamily, string> = {
  slot: "课位规则",
  distribution: "分布规则",
  teacher: "教师规则",
  class: "班级规则",
  combination: "组合规则",
};

interface RuleTemplate {
  id: RuleTemplateId;
  family: RuleFamily;
  category: RuleCategory;
  scope: RuleScope;
  operator: string;
  label: string;
  description: string;
}

const RULE_TEMPLATES: RuleTemplate[] = [
  {
    id: "slot_forbidden",
    family: "slot",
    category: "global",
    scope: "学科",
    operator: "禁止占用指定课位",
    label: "课位禁排",
    description:
      "禁止指定学科、教师、班级或全年级占用勾选的星期和节次（如语数外不排第8、9节）。",
  },
  {
    id: "subject_allowed_slots",
    family: "slot",
    category: "subject",
    scope: "学科",
    operator: "仅允许指定课位",
    label: "学科课位限制",
    description:
      "只限制「能排在哪些课位」。若要安排学科的上下午分布，请用「学科上下午分布」一条搞定，不必再重复添加本规则。",
  },
  {
    id: "teacher_forbidden_slots",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "禁止排课",
    label: "教师课位禁排",
    description: "禁止教师在指定星期和节次授课。",
  },
  {
    id: "teacher_daily_limit",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "每日课节上限",
    label: "工作日教师课节上限",
    description:
      "工作日每天最多 N 节；同时约束白天 1～7 节中间不能空节。可按学科批量覆盖任课老师。",
  },
  {
    id: "teacher_consecutive",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "要求连堂",
    label: "教师连堂",
    description: "要求教师在指定范围内形成连续课节，可选择同一班连堂或跨班连堂。",
  },
  {
    id: "teacher_preferred_weekdays",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "优先安排",
    label: "教师日期偏好",
    description: "让教师课程优先落在指定星期。",
  },
  {
    id: "teacher_multi_class_evening_adjacent",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "优先相邻安排",
    label: "多班教师晚课轮转",
    description: "多班教师的晚课按班级顺序轮转，让各班进度一致。",
  },
  {
    id: "teacher_evening_daytime_link",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "晚课日固定节次",
    label: "晚课日白天联动",
    description: "教师有晚课的那天，白天必须安排指定节次（如第7节）。",
  },
  {
    id: "teacher_period_minimum",
    family: "teacher",
    category: "teacher",
    scope: "教师",
    operator: "节次课时下限",
    label: "教师节次课时下限",
    description:
      "勾选教师后，全周在指定节次集合中合计至少 N 节（不必同一天；可限制星期）。",
  },
  {
    id: "subject_consecutive",
    family: "distribution",
    category: "subject",
    scope: "学科",
    operator: "要求连堂",
    label: "学科连堂",
    description:
      "勾选学科后，每周至少有 M 天出现连续 L 节（默认连续 2 节、至少 1 天）。",
  },
  {
    id: "class_slot_pattern",
    family: "distribution",
    category: "subject",
    scope: "学科",
    operator: "均衡分布",
    label: "学科上下午分布",
    description:
      "通用上下午对开：选择任意学科、星期与上午/下午节次；每班两种方向二选一。适合体育、实验课等需要错开时段的学科。",
  },
  {
    id: "class_allowed_subjects",
    family: "class",
    category: "class",
    scope: "班级",
    operator: "仅允许指定科目",
    label: "班级限定科目",
    description: "限定班级在指定课位只能安排选定科目。",
  },
  {
    id: "subject_prefer_early_periods",
    family: "distribution",
    category: "subject",
    scope: "学科",
    operator: "主科靠前",
    label: "主科尽量靠前",
    description: "选择主科，勾选尽量安排的节次；每个班每门课允许有几节排在这些节次之外。",
  },
  {
    id: "subject_gap_fill_late_periods",
    family: "distribution",
    category: "subject",
    scope: "学科",
    operator: "空节补活动课",
    label: "活动课补空节",
    description: "音美心优先落第8、9节自习位；只有前面会出现空节时才补进1～7节。",
  },
  {
    id: "class_evening_self_study_day",
    family: "class",
    category: "class",
    scope: "班级",
    operator: "选择自习日",
    label: "班级自习日",
    description: "在候选工作日中选择几天第8、9节保持自习（可空或音美心）。与晚自习无关，晚自习仍须排满。",
  },
  {
    id: "class_gap_free",
    family: "class",
    category: "global",
    scope: "全局",
    operator: "班级无空节",
    label: "班级无空堂",
    description: "指定星期第1～7节必须有课；第8、9节自习可空。",
  },
  {
    id: "slot_teacher_balance",
    family: "teacher",
    category: "global",
    scope: "全局",
    operator: "均衡分配",
    label: "节次教师均衡",
    description: "指定节次由不同教师分摊，限制每人上限。",
  },
  {
    id: "subject_evening_parity_pair",
    family: "combination",
    category: "evening",
    scope: "学科",
    operator: "单双周配对",
    label: "晚课单双周对课",
    description: "两门学科在同一晚课格单双周配对。",
  },
  {
    id: "subject_daytime_parity_pair",
    family: "combination",
    category: "subject",
    scope: "学科",
    operator: "白天单双周对课",
    label: "白天单双周对课",
    description:
      "勾选单周学科组、双周学科组，以及星期和节次。同一课位单双周各上一门；组内谁跟谁配对不规定。",
  },
  {
    id: "slot_teacher_role_required",
    family: "slot",
    category: "global",
    scope: "全局",
    operator: "必须安排",
    label: "课位教师角色",
    description:
      "勾选的星期和节次，每个班必须由本班班主任上课（目前仅支持班主任）。",
  },
];

const RULE_TEMPLATE_MAP = new Map(
  RULE_TEMPLATES.map((template) => [template.id, template]),
);

export interface GenericScheduleRule {
  id: string;
  category: RuleCategory;
  scope: RuleScope;
  family?: RuleFamily;
  target: string;
  kind: RuleKind;
  operator: string;
  relation: string;
  weekday: string;
  period: string;
  cycle: string;
  quantity: string;
  quantitySpec?: QuantitySpec;
  distributionTarget?: string;
  distributionSpec?: DistributionSpec;
  specificSlots?: SpecificSlot[];
    allowedSubjects?: string[];
    parityOddSubject?: string;
    parityEvenSubject?: string;
    parityOddSubjects?: string[];
    parityEvenSubjects?: string[];
    maxOutsidePreferred?: number;
  choiceCount?: number;
  requiredTeacherRole?: "head_teacher";
  priority: RulePriority;
  status: RuleStatus;
  enabled: boolean;
  title: string;
  note: string;
  rule_code?: SchedulingRuleCode;
}

export interface RuleGroup {
  id: string;
  name: string;
  grade_id: number | null;
  scope: string;
  term: string;
  rules: GenericScheduleRule[];
}

interface RuleGroupWorkbenchProps {
  slotOptions?: string[];
  academicYear?: string;
  term?: string;
  gridConfig?: SchedulingGridConfig;
  resources?: SchedulingResources;
  grades?: Grade[];
  /** 诊断侧栏点「去改规则」时打开对应综合规则，不自动跟排课失败绑定 */
  openGroupRequest?: { groupId: string; token: number } | null;
  /** 诊断侧栏应用建议后递增，刷新规则目录 */
  catalogEpoch?: number;
}

const LEGACY_STORAGE_KEY = "light-classroom.scheduling.rule-group.v1";
const catalogKey = (academicYear: string, term: string) =>
  `light-classroom.scheduling.rule-group-catalog:${academicYear}:${term}`;

/** 清掉历史本地规则缓存；综合规则只认后端。 */
const clearLegacyRuleGroupCache = (academicYear: string, term: string) => {
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    localStorage.removeItem(catalogKey(academicYear, term));
  } catch {
    /* ignore */
  }
};

export const gradeDisplayName = (grade?: Grade | null) => {
  if (!grade) return "未设置年级";
  return /年级$/.test(grade.name) ? grade.name : `${grade.name}年级`;
};

export const ruleGroupScopeLabel = (
  group: Pick<RuleGroup, "grade_id" | "scope">,
  grades: Grade[] = [],
  classes: Array<{ grade_id: number }> = [],
) => {
  if (!group.grade_id) return group.scope || "未设置年级";
  const grade = grades.find((item) => item.id === Number(group.grade_id));
  if (!grade) return group.scope || "未设置年级";
  const count = classes.filter(
    (item) => Number(item.grade_id) === Number(group.grade_id),
  ).length;
  const name = gradeDisplayName(grade);
  return count ? `${name} · ${count} 个班` : name;
};

export const inferGradeId = (
  group: Pick<RuleGroup, "name" | "scope" | "grade_id">,
  grades: Grade[] = [],
) => {
  if (group.grade_id != null) return Number(group.grade_id);
  const hay = `${group.name} ${group.scope}`;
  const found = grades.find(
    (grade) => hay.includes(grade.name) || hay.includes(grade.name.replace(/年级$/, "")),
  );
  return found?.id ?? null;
};

const summarizeGroup = (item: RuleGroup) => {
  const enabled = item.rules.filter((rule) => rule.enabled);
  const hard = enabled.filter((rule) => rule.priority === "hard").length;
  const soft = enabled.filter((rule) => rule.priority === "soft").length;
  const familyCounts = (Object.keys(RULE_FAMILY_LABELS) as RuleFamily[]).map(
    (family) => ({
      family,
      count: item.rules.filter(
        (rule) => (rule.family || familyForRule(rule)) === family,
      ).length,
    }),
  );
  const typeSummary = [
    ...new Set(
      item.rules.map(
        (rule) => RULE_FAMILY_LABELS[rule.family || familyForRule(rule)],
      ),
    ),
  ].join(" · ");
  return { enabled, hard, soft, familyCounts, typeSummary };
};

const ruleCodeForRule = (
  rule: Pick<
    GenericScheduleRule,
    "id" | "operator" | "family" | "rule_code" | "distributionSpec"
  >,
): SchedulingRuleCode => {
  if (rule.rule_code && rule.rule_code !== "manual_review") return rule.rule_code;
  if (rule.id === "R04-continuity" || String(rule.id).endsWith("-continuity"))
    return "teacher_gap_free";
  if (rule.id === "R04-pack") return "class_gap_free";
  if (rule.id === "R11-e") return "teacher_forbidden_slots";
  if (rule.id === "R17-02") return "slot_teacher_balance";
  if (rule.id === "R19-01" || rule.id === "R19-02")
    return "teacher_preferred_weekdays";
  if (rule.id === "R22") return "subject_evening_parity_pair";
  if (rule.id.startsWith("R01-") || rule.id === "R18-lang") return "slot_forbidden";
  if (rule.id === "R05") return "subject_consecutive";
  if (rule.id === "R08-01") return "subject_allowed_slots";
  if (rule.id === "R08-02") return "class_slot_pattern";
  if (rule.id === "R12") return "teacher_forbidden_slots";
  if (
    rule.id === "R13" ||
    rule.id === "R16" ||
    rule.id === "R17-01" ||
    rule.id === "R20"
  )
    return "teacher_forbidden_slots";
  if (rule.id === "R15") return "teacher_multi_class_evening_adjacent";
  if (rule.id === "R06" || rule.id === "R07") return "teacher_forbidden_slots";
  if (rule.id === "R14") return "teacher_forbidden_slots";
  if (rule.id === "R04") return "teacher_daily_limit";
  if (
    rule.operator === "保持连续" ||
    rule.operator === "尽量连续"
  )
    return "teacher_consecutive";
  if (rule.id === "R18" || rule.id === "R18-b" || rule.id === "R18-s") return "class_allowed_subjects";
  if (rule.id === "R23") return "subject_prefer_early_periods";
  if (rule.id === "R24") return "subject_gap_fill_late_periods";
  if (rule.id === "R19-03") return "class_evening_self_study_day";
  if (rule.id === "R02") return "slot_teacher_role_required";
  if (rule.id === "R10") return "teacher_forbidden_slots";
  if (rule.id === "R10-b") return "teacher_evening_daytime_link";
  if (rule.id === "R10-c" || rule.operator === "节次课时下限")
    return "teacher_period_minimum";
  if (
    rule.operator === "均衡分布" ||
    rule.distributionSpec?.target === "morning-afternoon"
  )
    return "class_slot_pattern";
  return "manual_review";
};

const familyForRule = (
  rule: Pick<
    GenericScheduleRule,
    "id" | "category" | "scope" | "kind" | "operator" | "rule_code"
  >,
): RuleFamily => {
  // R04 等是「学科作用对象 + 教师约束」，不能按 scope=学科掉进课位类别，
  // 否则排课目标选项对不上，会露出 daily-limit 这类内部编码。
  if (
    rule.id === "R04" ||
    (typeof rule.id === "string" &&
      rule.id.startsWith("R04-") &&
      rule.id !== "R04-pack") ||
    rule.rule_code === "teacher_daily_limit" ||
    rule.rule_code === "teacher_gap_free" ||
    rule.rule_code === "teacher_period_minimum" ||
    rule.rule_code === "teacher_multi_class_evening_adjacent"
  ) {
    return "teacher";
  }
  if (rule.kind === "课时") return "distribution";
  if (rule.kind === "配对") return "combination";
  if (rule.category === "class") return "class";
  if (rule.category === "teacher" || rule.scope === "教师") return "teacher";
  if (rule.category === "evening" || rule.scope === "课位") return "slot";
  return "slot";
};

const makeRule = (
  rule: Omit<GenericScheduleRule, "enabled"> & { enabled?: boolean },
): GenericScheduleRule => ({
  enabled: true,
  ...rule,
  family: rule.family || familyForRule(rule),
  rule_code: rule.rule_code || ruleCodeForRule(rule),
});

const DEFAULT_RULES: GenericScheduleRule[] = [
  makeRule({
    id: "R01-01",
    category: "subject",
    scope: "学科",
    target: "语文",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周一",
    period: "第6、7节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "语文备课时段禁排",
    note: "语文备课时间为周一第6、7节，备课时段不排语文课。",
  }),
  makeRule({
    id: "R01-02",
    category: "subject",
    scope: "学科",
    target: "英语",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周二",
    period: "第6、7节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "英语备课时段禁排",
    note: "英语备课时间为周二第6、7节，备课时段不排英语课。",
  }),
  makeRule({
    id: "R01-03",
    category: "subject",
    scope: "学科",
    target: "数学",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周三",
    period: "第6、7节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "数学备课时段禁排",
    note: "数学备课时间为周三第6、7节，备课时段不排数学课。",
  }),
  makeRule({
    id: "R01-04",
    category: "subject",
    scope: "学科",
    target: "物理",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周二",
    period: "第3、4节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "物理备课时段禁排",
    note: "物理备课时间为周二第3、4节，备课时段不排物理课。",
  }),
  makeRule({
    id: "R01-05",
    category: "subject",
    scope: "学科",
    target: "化学",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周五",
    period: "第3、4节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "化学备课时段禁排",
    note: "化学备课时间为周五第3、4节，备课时段不排化学课。",
  }),
  makeRule({
    id: "R01-06",
    category: "subject",
    scope: "学科",
    target: "生物",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周四",
    period: "第3、4节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "生物备课时段禁排",
    note: "生物备课时间为周四第3、4节，备课时段不排生物课。",
  }),
  makeRule({
    id: "R01-07",
    category: "subject",
    scope: "学科",
    target: "政治",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周三",
    period: "第4、5节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "政治备课时段禁排",
    note: "政治备课时间为周三第4、5节，备课时段不排政治课。",
  }),
  makeRule({
    id: "R01-08",
    category: "subject",
    scope: "学科",
    target: "历史",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周五",
    period: "第6、7节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "历史备课时段禁排",
    note: "历史备课时间为周五第6、7节，备课时段不排历史课。",
  }),
  makeRule({
    id: "R01-09",
    category: "subject",
    scope: "学科",
    target: "地理",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周四",
    period: "第6、7节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "地理备课时段禁排",
    note: "地理备课时间为周四第6、7节，备课时段不排地理课。",
  }),
  makeRule({
    id: "R02",
    category: "global",
    scope: "全局",
    family: "slot",
    target: "全年级",
    kind: "固定",
    operator: "必须安排",
    relation: "无",
    weekday: "周六",
    period: "第10节",
    cycle: "每周",
    quantity: "每班 1 节",
    requiredTeacherRole: "head_teacher",
    priority: "hard",
    status: "pass",
    title: "周六晚自习安排班主任",
    note: "每个班级的周六晚自习（第10节）必须由本班班主任负责。",
    rule_code: "slot_teacher_role_required",
  }),
  makeRule({
    id: "R04",
    family: "teacher",
    category: "global",
    scope: "学科",
    target:
      "语文 / 数学 / 英语 / 物理 / 化学 / 生物 / 政治 / 历史 / 地理 / 音乐 / 美术 / 心理",
    kind: "连续",
    operator: "每日课节上限",
    relation: "且",
    weekday: "周一至周五",
    period: "白天课",
    cycle: "每周",
    quantity: "每天最多 3 节",
    distributionSpec: { target: "daily-limit", maxLessonsPerDay: 3 },
    priority: "hard",
    status: "pass",
    title: "工作日教师课节上限",
    note: "学科模式：勾选学科后，这些学科的任课老师都受约束——工作日每天最多 3 节，白天 1～7 节不能空节。一般不要勾体育。也可改成「教师」直接点名。",
    rule_code: "teacher_daily_limit",
  }),
  makeRule({
    id: "R04-pack",
    category: "global",
    scope: "全局",
    target: "高一全年级",
    kind: "连续",
    operator: "班级无空节",
    relation: "无空节",
    weekday: "周一至周六",
    period: "第1～7节",
    cycle: "每周",
    quantity: "1～7节必须有课",
    priority: "hard",
    status: "pass",
    title: "班级1至7节无空堂",
    note: "周一至周六第1～7节必须有课；第8、9节可空。周六单双周都要满。教师工作日课节上限见 R04。",
    rule_code: "class_gap_free",
  }),
  makeRule({
    id: "R05",
    category: "subject",
    scope: "学科",
    family: "distribution",
    target: "数学",
    kind: "连续",
    operator: "要求连堂",
    relation: "且",
    weekday: "周一至周五",
    period: "未配置具体课位",
    cycle: "每周",
    quantity: "不限定",
    distributionSpec: {
      target: "consecutive",
      consecutiveLength: 2,
      minimumDays: 1,
    },
    priority: "hard",
    status: "pass",
    title: "学科连堂",
    note: "所选学科每周至少有1天安排连续2节，周课时数量以课时管理配置为准。",
  }),
  makeRule({
    id: "R06",
    category: "teacher",
    scope: "教师",
    target: "黄淑梅",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周三至周六",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "黄淑梅晚课仅周一周二",
    note: "周一、周二晚自习必须各上一班（1班/2班可对调）；周三到周六第10节禁排。",
  }),
  makeRule({
    id: "R07",
    category: "teacher",
    scope: "教师",
    target: "杨元元",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周三至周六",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "杨元元晚课仅周一周二",
    note: "周一、周二晚自习必须各上一班（3班/4班可对调）；周三到周六第10节禁排。",
  }),
  makeRule({
    id: "R08-02",
    category: "subject",
    scope: "学科",
    family: "distribution",
    target: "体育",
    kind: "固定",
    operator: "均衡分布",
    relation: "无",
    weekday: "周二、周四",
    period: "第3、4、6、7节",
    cycle: "每周",
    quantity: "不限定",
    distributionSpec: {
      target: "morning-afternoon",
      patternMode: "either-direction",
      patternWeekdays: [2, 4],
      morningPeriods: [3, 4],
      afternoonPeriods: [6, 7],
    },
    priority: "hard",
    status: "pass",
    title: "学科上下午分布",
    note: "允许课位 = 所选星期 × 上午/下午节次；每班两种交叉方向二选一。周课时从课时管理读取。",
    rule_code: "class_slot_pattern",
  }),
  makeRule({
    id: "R09",
    category: "teacher",
    scope: "教师",
    target: "王璐",
    kind: "固定",
    operator: "固定到指定课位",
    relation: "且",
    weekday: "周二 / 周四",
    period: "周二6、7；周四3、4",
    cycle: "每周",
    quantity: "跨年级",
    priority: "hard",
    status: "pass",
    title: "王璐跨年级体育课位",
    note: "王璐仅允许周二6、7节和周四3、4节，其余白天禁排。",
    specificSlots: [
      { weekday: 1, periods: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
      { weekday: 2, periods: [1, 2, 3, 4, 5, 8, 9] },
      { weekday: 3, periods: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
      { weekday: 4, periods: [1, 2, 5, 6, 7, 8, 9] },
      { weekday: 5, periods: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
      { weekday: 6, periods: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
    ],
  }),
  makeRule({
    id: "R10",
    category: "teacher",
    scope: "教师",
    target: "黄丽娟",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周一至周六",
    period: "第1、2、6节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "黄丽娟不排1、2、6节",
    note: "黄丽娟全周不排第1、2、6节。",
    rule_code: "teacher_forbidden_slots",
  }),
  makeRule({
    id: "R10-b",
    category: "teacher",
    scope: "教师",
    target: "黄丽娟",
    kind: "固定",
    operator: "晚课日固定节次",
    relation: "且",
    weekday: "有晚课日",
    period: "第7节",
    cycle: "每周",
    quantity: "晚课日 1 节",
    priority: "hard",
    status: "pass",
    title: "黄丽娟晚课日排第7节",
    note: "有晚课的那天，白天必须安排第7节；不要求当天再凑3、4、5节。",
    rule_code: "teacher_evening_daytime_link",
  }),
  makeRule({
    id: "R10-c",
    category: "teacher",
    scope: "教师",
    target: "黄丽娟",
    kind: "课时",
    operator: "节次课时下限",
    relation: "无",
    weekday: "周一至周五",
    period: "第3、4、5节",
    cycle: "每周",
    quantity: "至少 2 节",
    priority: "hard",
    status: "pass",
    title: "黄丽娟第3/4/5节至少2节",
    note: "工作日第3、4、5节合计至少2节，不含周六，不必与晚课同一天。",
    family: "teacher",
    rule_code: "teacher_period_minimum",
    quantitySpec: { amount: 2, unit: "section", distribution: "none" },
  }),
  makeRule({
    id: "R11-e",
    category: "evening",
    scope: "教师",
    target: "王淑华",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周一 / 周三至周六",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "王淑华晚课固定周二",
    note: "老师第9条：晚课只排星期二（其余晚自习禁排）。",
  }),
  makeRule({
    id: "R12",
    category: "teacher",
    scope: "教师",
    target: "毛宇莹",
    kind: "禁排",
    operator: "禁止占用指定课位",
    relation: "无",
    weekday: "周一至周六",
    period: "已配置具体课位",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "毛宇莹不可用课位",
    specificSlots: [
      { weekday: 1, periods: [1, 3, 5] },
      { weekday: 2, periods: [1, 5, 7, 8] },
      { weekday: 3, periods: [1, 2, 5] },
      { weekday: 4, periods: [1, 5, 6] },
      { weekday: 5, periods: [1, 2, 5] },
      { weekday: 6, periods: [1, 3, 5] },
    ],
    note: "第1、5节不排；另一个年级已占用的课位也不能再安排毛宇莹。",
  }),
  makeRule({
    id: "R13",
    category: "teacher",
    scope: "教师",
    target: "陈晓辉",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "全周",
    period: "第5节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "陈晓辉不排第5节",
    note: "陈晓辉全周不排第5节。",
  }),
  makeRule({
    id: "R14",
    category: "teacher",
    scope: "教师",
    target: "屈金",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周二 / 周三 / 周五 / 周六",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "屈金周一周四晚课都要上",
    note: "四个班地理各 0.5：单周两节、双周两节。只能排周一和周四，所以这两天单双周都要有课，四个班可对调。周二、三、五、六晚自习禁排。",
  }),
  makeRule({
    id: "R15",
    category: "teacher",
    scope: "教师",
    family: "teacher",
    target: "多班教师",
    kind: "固定",
    operator: "优先相邻安排",
    relation: "班级轮转",
    weekday: "工作日",
    period: "晚课",
    cycle: "每周",
    quantity: "至少2个班级",
    priority: "hard",
    status: "pass",
    title: "多班教师晚课轮转",
    note: "硬约束：同一老师多个班的晚课按固定顺序轮转，让各班进度一致。例如带 A/B/C/D，上完 A 再上 B、再 C、再 D，然后回到 A；转完一圈前不能重复某班。中间可以空日子。已有晚课星期限定的教师不套本条。体育、自主学习不计。",
  }),
  makeRule({
    id: "R16",
    category: "teacher",
    scope: "教师",
    target: "褚光庆",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "全周",
    period: "第1节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "褚光庆不排第1节",
    note: "硬约束、白天课：褚光庆全周（含周六）都不排第1节，他任教的各班化学都算。不管晚自习。",
  }),
  makeRule({
    id: "R17-01",
    category: "teacher",
    scope: "教师",
    family: "teacher",
    target: "班主任",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "全周",
    period: "第5节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "本班第五节不排班主任",
    note: "硬约束、白天课：班主任只禁自己当班主任的那个班的第5节（含周六）；在其它班当科任可以排第5节，用来分担科任第5节压力。晚自习不管。",
  }),
  makeRule({
    id: "R17-02",
    category: "teacher",
    scope: "教师",
    family: "teacher",
    target: "科任教师",
    kind: "固定",
    operator: "均衡分配",
    relation: "无",
    weekday: "全周",
    period: "第5节",
    cycle: "每周",
    quantity: "每人最多 2 节",
    quantitySpec: { amount: 2, unit: "section", distribution: "none" },
    priority: "hard",
    status: "pass",
    title: "第5节教师每周最多2节",
    note: "硬约束、白天课：全周（含周六）每名任课教师第5节最多 2 节，多出来的算违规。班主任本班第5节见 R17-01；班主任在他班当科任也计入这 2 节。生成时会尽量摊给不同老师。晚自习不管。",
    rule_code: "slot_teacher_balance",
  }),
  makeRule({
    id: "R18",
    category: "class",
    scope: "班级",
    target: "高一（10）班",
    kind: "禁排",
    operator: "仅允许指定科目",
    relation: "且",
    weekday: "周一 / 周二",
    period: "第8、9节",
    cycle: "每周",
    quantity: "仅音乐 / 美术 / 心理",
    allowedSubjects: ["音乐", "美术", "心理"],
    priority: "hard",
    status: "pass",
    title: "10班周一周二第8、9节仅活动课",
    note: "硬约束、白天课：只约束高一（10）班，周一和周二的第8、9节。格子可以空着当自习；如果排课，只能是音乐、美术、心理。不是全年级，也不强制排满。第8、9节不是晚自习。",
  }),
  makeRule({
    id: "R18-b",
    category: "class",
    scope: "班级",
    target: "高一（10）班",
    kind: "禁排",
    operator: "禁止安排指定节次",
    relation: "且",
    weekday: "周四",
    period: "第8、9节",
    cycle: "每周",
    quantity: "不排课",
    priority: "hard",
    status: "pass",
    title: "10班周四第8、9节不排课",
    note: "硬约束、白天课：只约束高一（10）班星期四第8、9节。这两格必须空着当自习，音乐、美术、心理也不能排。周一、周二仍按 R18（可空，若排只能活动课）。",
  }),
  makeRule({
    id: "R18-s",
    category: "class",
    scope: "班级",
    target: "高一全年级",
    kind: "禁排",
    operator: "仅允许指定科目",
    relation: "且",
    weekday: "周一至周五",
    period: "第8、9节",
    cycle: "每周",
    quantity: "仅音乐 / 美术 / 心理",
    allowedSubjects: ["音乐", "美术", "心理"],
    enabled: false,
    priority: "soft",
    status: "pass",
    title: "工作日第8、9节仅活动课（已停用）",
    note: "不做硬约束：全年级第8、9节禁主科会与现有教师禁排冲突导致无解。10班周一/二仍按 R18；周四按 R18-b。",
    rule_code: "class_allowed_subjects",
  }),
  makeRule({
    id: "R18-lang",
    category: "subject",
    scope: "学科",
    family: "slot",
    target: "语文 / 数学 / 英语",
    kind: "禁排",
    operator: "禁止占用指定课位",
    relation: "无",
    weekday: "周一至周五",
    period: "第8、9节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "语数外不排第8、9节",
    note: "硬约束：语文、数学、英语不能排在工作日第8、9节；政地生化等可以。第8节可空、第9节有课也允许。",
    rule_code: "slot_forbidden",
  }),
  makeRule({
    id: "R19-01",
    category: "teacher",
    scope: "教师",
    target: "张卓",
    kind: "固定",
    operator: "优先安排",
    relation: "无",
    weekday: "周一",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "10班 1 节",
    priority: "hard",
    status: "pass",
    title: "张卓10班周一晚课",
    note: "硬约束、晚自习钉位：高一（10）班星期一第10节必须由张卓上，用他自己的本班学科额度，不能改成自主学习。不要求他把所有晚课都排周一；7班钉位见 R19-02。其它课要给这个格子让路。",
  }),
  makeRule({
    id: "R19-02",
    category: "teacher",
    scope: "教师",
    target: "张卓",
    kind: "固定",
    operator: "优先安排",
    relation: "无",
    weekday: "周二",
    period: "第10节晚自习",
    cycle: "每周",
    quantity: "7班 1 节",
    priority: "hard",
    status: "pass",
    title: "张卓7班周二晚课",
    note: "固定钉位：高一（7）班星期二晚自习由张卓上课。与 R19-01 同时硬满足；调整时优先保周一/周二钉位。",
  }),
  makeRule({
    id: "R19-03",
    category: "class",
    scope: "班级",
    target: "高一（10）班",
    kind: "固定",
    operator: "选择自习日",
    relation: "无",
    weekday: "周三至周五",
    period: "第8、9节",
    cycle: "每周",
    quantity: "1天",
    choiceCount: 1,
    priority: "hard",
    status: "unresolved",
    title: "10班自习日",
    note: "高一（10）班周三至周五至少一天第8、9节保持自习。晚自习仍按单双周6+6排满，空晚自习不算自习。",
    rule_code: "class_evening_self_study_day",
  }),
  makeRule({
    id: "R20",
    category: "teacher",
    scope: "教师",
    target: "赵永丽",
    kind: "禁排",
    operator: "禁止排课",
    relation: "无",
    weekday: "周三",
    period: "第8、9节",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "赵永丽周三第8、9节不排课",
    note: "星期三第8、9节不排课（白天自习位）。",
  }),
  makeRule({
    id: "R21",
    category: "evening",
    scope: "教师",
    target: "董舰洋",
    kind: "禁排",
    operator: "禁止安排晚课",
    relation: "无",
    weekday: "周一",
    period: "晚课",
    cycle: "每周",
    quantity: "不限定",
    priority: "hard",
    status: "pass",
    title: "董舰洋周一晚课禁排",
    note: "董舰洋周一第10节晚自习不排课。",
    rule_code: "teacher_forbidden_slots",
  }),
  makeRule({
    id: "R22",
    category: "evening",
    scope: "学科",
    target: "物理 / 历史",
    kind: "配对",
    operator: "单双周配对",
    relation: "同一晚课格",
    weekday: "全周",
    period: "晚课",
    cycle: "单周 / 双周",
    quantity: "单物双史或单史双物",
    priority: "hard",
    status: "pass",
    title: "学科晚课单双周配对",
    note: "同一晚课格内的两组学科按单双周配对；单周/双周对应关系可按配置调整。",
    rule_code: "subject_evening_parity_pair",
  }),
  makeRule({
    id: "R23",
    category: "subject",
    scope: "学科",
    target: "语文 / 数学 / 英语 / 物理 / 化学 / 生物 / 政治 / 历史 / 地理",
    kind: "固定",
    operator: "主科靠前",
    relation: "无",
    weekday: "全周",
    period: "第1节、第2节、第3节、第4节、第5节",
    cycle: "每周",
    quantity: "允许 2 节不在所选节次",
    maxOutsidePreferred: 2,
    priority: "soft",
    status: "pass",
    title: "主科靠前",
    note: "所选主科尽量排进勾选的节次；每个班每门课超出「允许不在这些节次」的数量会计分（软）或判违规（硬）。",
    rule_code: "subject_prefer_early_periods",
  }),
  makeRule({
    id: "R24",
    category: "subject",
    scope: "学科",
    target: "音乐 / 美术 / 心理",
    kind: "固定",
    operator: "空节补活动课",
    relation: "无",
    weekday: "全周",
    period: "白天课",
    cycle: "每周",
    quantity: "第8、9节优先",
    priority: "soft",
    status: "pass",
    title: "活动课排第8、9节",
    note: "音乐、美术、心理尽量排第8、9节；1～7仍空才允许补进去。",
    rule_code: "subject_gap_fill_late_periods",
  }),
];

const SCHEDULE_SUBJECTS = [
  "各学科",
  "语文",
  "数学",
  "英语",
  "物理",
  "化学",
  "生物",
  "政治",
  "历史",
  "地理",
  "体育",
  "音乐",
  "美术",
  "心理",
];
const SCHEDULE_TEACHERS = [
  "黄淑梅",
  "杨元元",
  "王璐",
  "黄丽娟",
  "王淑华",
  "毛宇莹",
  "陈晓辉",
  "屈金",
  "褚光庆",
  "赵永丽",
  "董舰洋",
  "多班教师",
  "科任教师",
  "班主任",
];
const SCHEDULE_CLASSES = ["高一（1）班", "高一（7）班", "高一（10）班"];
const WEEKDAY_OPTIONS = [
  "周一",
  "周二",
  "周三",
  "周四",
  "周五",
  "周六",
  "周日",
];
const UNRESOLVED_PERIOD = "未配置具体课位";
const PERIOD_ENUMS = Array.from(
  { length: 9 },
  (_, index) => `第${index + 1}节`,
);
const PERIOD_OPTIONS = PERIOD_ENUMS;
const periodSelections = (value: string) => {
  if (!value) return [];
  if (
    value === UNRESOLVED_PERIOD ||
    value === "未指定" ||
    value === "白天课" ||
    value === "晚课" ||
    value === "早课"
  )
    return [];
  if (PERIOD_OPTIONS.includes(value)) return [value];
  // 支持第10节及区间「第1～7节」；旧正则只认单位数，会把「第10节」误解析成第1节。
  const parsed = [
    ...value.matchAll(
      /(?:第|周[一二三四五六日])([1-9]\d*(?:[、,，～~\-][1-9]\d*)*)节?/g,
    ),
  ].flatMap((match) => {
    const token = match[1];
    const range = token.match(/^(\d+)[～~\-](\d+)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      const lo = Math.min(start, end);
      const hi = Math.max(start, end);
      return Array.from({ length: hi - lo + 1 }, (_, index) => `第${lo + index}节`);
    }
    return token.split(/[、,，]/).map((period) => `第${period}节`);
  });
  return [...new Set(parsed)];
};
const specificSlotSummary = (slots: SpecificSlot[] = []) =>
  slots
    .filter((slot) => slot.periods.length)
    .sort((left, right) => left.weekday - right.weekday)
    .map(
      (slot) =>
        `${WEEKDAY_OPTIONS[slot.weekday - 1]}第${slot.periods.join("、")}节`,
    )
    .join("；");
const getTargetOptionsFromResources = (
  scope: RuleScope,
  currentTarget = "",
  slotOptions: string[] = [],
  resources?: SchedulingResources,
) => {
  const extra = currentTarget.split(/\s*[\/、]\s*/).filter(Boolean);
  const base =
    scope === "课位"
      ? slotOptions
      : scope === "学科"
        ? resources?.subjects.map((item) => item.name) || SCHEDULE_SUBJECTS
        : scope === "教师"
          ? [
              ...(resources?.teachers.map((item) => item.name) ||
                SCHEDULE_TEACHERS),
              "多班教师",
            ]
          : scope === "班级"
            ? resources?.classes.map((item) => item.name) || SCHEDULE_CLASSES
            : ["全局规则", "科任教师", "班主任", "多班教师"];
  return [
    ...new Set(
      [...base, ...extra].filter(
        (value) => Boolean(value) && !value.includes(" / "),
      ),
    ),
  ];
};

/** 不可改字段：用只读文案/标签，避免禁用下拉还露出箭头 */
function ReadonlyValue({
  value,
  values,
  empty = "未指定",
}: {
  value?: string;
  values?: string[];
  empty?: string;
}) {
  const items = (values ?? (value ? [value] : [])).filter(Boolean);
  if (!items.length) {
    return <div className="rule-group-readonly">{empty}</div>;
  }
  if (items.length === 1) {
    return <div className="rule-group-readonly">{items[0]}</div>;
  }
  return (
    <div className="rule-group-readonly is-chips">
      {items.map((item) => (
        <Tag key={item}>{item}</Tag>
      ))}
    </div>
  );
}

const DEFAULT_SLOT_PATTERN = {
  patternWeekdays: [2, 4],
  morningPeriods: [3, 4],
  afternoonPeriods: [6, 7],
};

const weekdayLabelFromCodeList = (codes: number[]) =>
  codes
    .slice()
    .sort((left, right) => left - right)
    .map((code) => WEEKDAY_OPTIONS[code - 1])
    .filter(Boolean)
    .join("、");

const periodLabelFromCodeList = (codes: number[]) =>
  codes
    .slice()
    .sort((left, right) => left - right)
    .map((code) => `第${code}节`)
    .join("、");

const resolveSlotPattern = (
  spec?: DistributionSpec,
  weekdayText = "",
  periodText = "",
) => {
  const weekdays = (
    spec?.patternWeekdays?.length
      ? spec.patternWeekdays
      : weekdayCodes(weekdayText)
  )
    .filter((code) => code >= 1 && code <= 7)
    .sort((left, right) => left - right);
  const morning = (
    spec?.morningPeriods?.length
      ? spec.morningPeriods
      : periodCodes(periodText).slice(0, Math.ceil(periodCodes(periodText).length / 2) || 2)
  )
    .map(Number)
    .filter((code) => code >= 1)
    .sort((left, right) => left - right);
  const afternoon = (
    spec?.afternoonPeriods?.length
      ? spec.afternoonPeriods
      : periodCodes(periodText).slice(Math.ceil(periodCodes(periodText).length / 2) || 2)
  )
    .map(Number)
    .filter((code) => code >= 1)
    .sort((left, right) => left - right);
  const safeWeekdays = weekdays.length
    ? weekdays
    : DEFAULT_SLOT_PATTERN.patternWeekdays;
  const safeMorning = morning.length
    ? morning
    : DEFAULT_SLOT_PATTERN.morningPeriods;
  const safeAfternoon = afternoon.length
    ? afternoon
    : DEFAULT_SLOT_PATTERN.afternoonPeriods;
  const periods = [...new Set([...safeMorning, ...safeAfternoon])].sort(
    (left, right) => left - right,
  );
  return {
    weekdays: safeWeekdays,
    morning: safeMorning,
    afternoon: safeAfternoon,
    periods,
  };
};

/** 交叉对开：日1上午+日2下午 / 日1下午+日2上午 */
const buildEitherDirectionAlternatives = (
  weekdays: number[],
  morning: number[],
  afternoon: number[],
) => {
  const [day1, day2] = weekdays.slice(0, 2);
  if (!day1 || !day2 || !morning.length || !afternoon.length) return [];
  return [
    [
      { weekdays: [day1], periods: morning, count: 1 },
      { weekdays: [day2], periods: afternoon, count: 1 },
    ],
    [
      { weekdays: [day1], periods: afternoon, count: 1 },
      { weekdays: [day2], periods: morning, count: 1 },
    ],
  ];
};

const parseSlotPatternFromApi = (apiRule: {
  weekdays?: number[];
  periods?: number[];
  params?: Record<string, unknown>;
}): DistributionSpec => {
  const weekdays = (apiRule.weekdays || []).filter(Boolean);
  const periods = (apiRule.periods || []).filter(Boolean);
  const alts = apiRule.params?.alternatives;
  let morning = DEFAULT_SLOT_PATTERN.morningPeriods;
  let afternoon = DEFAULT_SLOT_PATTERN.afternoonPeriods;
  if (Array.isArray(alts) && Array.isArray(alts[0]) && alts[0].length >= 2) {
    const first = alts[0][0] as { periods?: number[] };
    const second = alts[0][1] as { periods?: number[] };
    const left = (first.periods || []).map(Number);
    const right = (second.periods || []).map(Number);
    const avg = (values: number[]) =>
      values.reduce((sum, item) => sum + item, 0) / (values.length || 1);
    if (left.length && right.length) {
      if (avg(left) <= avg(right)) {
        morning = left;
        afternoon = right;
      } else {
        morning = right;
        afternoon = left;
      }
    }
  } else if (periods.length) {
    const sorted = [...periods].sort((left, right) => left - right);
    const mid = Math.max(1, Math.ceil(sorted.length / 2));
    morning = sorted.slice(0, mid);
    afternoon = sorted.slice(mid);
  }
  return {
    target: "morning-afternoon",
    patternMode: "either-direction",
    patternWeekdays: weekdays.length
      ? weekdays
      : DEFAULT_SLOT_PATTERN.patternWeekdays,
    morningPeriods: morning,
    afternoonPeriods: afternoon.length
      ? afternoon
      : DEFAULT_SLOT_PATTERN.afternoonPeriods,
  };
};

/** 通用上下午分布编辑：星期 + 上午/下午节次 → 自动生成两种交叉方案 */
function SlotPatternEditor({
  subjects,
  weekdayOptions,
  periodOptions,
  spec,
  onChange,
}: {
  subjects: string;
  weekdayOptions: string[];
  periodOptions: string[];
  spec?: DistributionSpec;
  onChange: (next: {
    distributionSpec: DistributionSpec;
    weekday: string;
    period: string;
  }) => void;
}) {
  const pattern = resolveSlotPattern(spec);
  const dayLabels = pattern.weekdays.map(
    (code) => WEEKDAY_OPTIONS[code - 1] || `周${code}`,
  );
  const amSet = new Set(pattern.morning);
  const alternatives = buildEitherDirectionAlternatives(
    pattern.weekdays,
    pattern.morning,
    pattern.afternoon,
  );
  const emit = (partial: {
    patternWeekdays?: number[];
    morningPeriods?: number[];
    afternoonPeriods?: number[];
  }) => {
    const next = resolveSlotPattern({
      target: "morning-afternoon",
      patternMode: "either-direction",
      patternWeekdays: partial.patternWeekdays ?? pattern.weekdays,
      morningPeriods: partial.morningPeriods ?? pattern.morning,
      afternoonPeriods: partial.afternoonPeriods ?? pattern.afternoon,
    });
    onChange({
      distributionSpec: {
        target: "morning-afternoon",
        patternMode: "either-direction",
        patternWeekdays: next.weekdays,
        morningPeriods: next.morning,
        afternoonPeriods: next.afternoon,
      },
      weekday: weekdayLabelFromCodeList(next.weekdays),
      period: periodLabelFromCodeList(next.periods),
    });
  };
  const planLabel = (groups: Array<{ weekdays: number[]; periods: number[] }>) =>
    groups
      .map((group) => {
        const day = WEEKDAY_OPTIONS[(group.weekdays[0] || 1) - 1] || "";
        const band =
          group.periods.every((item) => amSet.has(item)) ? "上午" : "下午";
        return `${day}${band}（${group.periods.join("/")}节）`;
      })
      .join(" + ");

  return (
    <div className="rule-group-slot-pattern">
      <div className="rule-group-slot-pattern-fields">
        <label>
          <span>对开星期</span>
          <Select
            mode="multiple"
            maxTagCount="responsive"
            value={dayLabels}
            onChange={(values: string[]) => {
              const codes = values
                .map((name) => WEEKDAY_OPTIONS.indexOf(name) + 1)
                .filter((code) => code > 0)
                .sort((left, right) => left - right)
                .slice(0, 2);
              emit({ patternWeekdays: codes });
            }}
            options={weekdayOptions.map((value) => ({ value, label: value }))}
            placeholder="请选 2 个星期"
          />
        </label>
        <label>
          <span>上午节次</span>
          <Select
            mode="multiple"
            maxTagCount="responsive"
            value={pattern.morning.map((code) => `第${code}节`)}
            onChange={(values: string[]) =>
              emit({
                morningPeriods: values
                  .map((item) => Number(item.match(/\d+/)?.[0]))
                  .filter((code) => Number.isInteger(code)),
              })
            }
            options={periodOptions.map((value) => ({ value, label: value }))}
            placeholder="如 第3节、第4节"
          />
        </label>
        <label>
          <span>下午节次</span>
          <Select
            mode="multiple"
            maxTagCount="responsive"
            value={pattern.afternoon.map((code) => `第${code}节`)}
            onChange={(values: string[]) =>
              emit({
                afternoonPeriods: values
                  .map((item) => Number(item.match(/\d+/)?.[0]))
                  .filter((code) => Number.isInteger(code)),
              })
            }
            options={periodOptions.map((value) => ({ value, label: value }))}
            placeholder="如 第6节、第7节"
          />
        </label>
      </div>
      {pattern.weekdays.length === 2 && pattern.periods.length > 0 ? (
        <>
          <div className="rule-group-slot-pattern-head">
            <strong>允许课位预览</strong>
            <span>
              {(subjects || "所选学科") +
                `只落在 ${weekdayLabelFromCodeList(pattern.weekdays)} 的 ${periodLabelFromCodeList(pattern.periods)}`}
            </span>
          </div>
          <div
            className="rule-group-slot-pattern-grid"
            style={
              {
                ["--slot-pattern-days" as string]: String(pattern.weekdays.length),
              } as Record<string, string>
            }
            aria-label="允许课位示意"
          >
            <div className="rule-group-slot-pattern-row is-head">
              <div className="rule-group-slot-pattern-period">节次</div>
              {dayLabels.map((day) => (
                <div key={day} className="rule-group-slot-pattern-day">
                  {day}
                </div>
              ))}
            </div>
            {pattern.periods.map((period) => (
              <div key={`row-${period}`} className="rule-group-slot-pattern-row">
                <div className="rule-group-slot-pattern-period">
                  第{period}节
                  <small>{amSet.has(period) ? "上午" : "下午"}</small>
                </div>
                {pattern.weekdays.map((day) => (
                  <div
                    key={`${day}-${period}`}
                    className={`rule-group-slot-pattern-cell ${amSet.has(period) ? "is-am" : "is-pm"}`}
                  >
                    可排
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="rule-group-slot-pattern-plans">
            {alternatives.map((groups, index) => (
              <article key={index}>
                <span>方案 {index === 0 ? "A" : "B"}</span>
                <strong>{planLabel(groups)}</strong>
                <small>每班选其中一种</small>
              </article>
            ))}
          </div>
        </>
      ) : (
        <p className="rule-group-slot-pattern-note is-warn">
          请选择恰好 2 个星期，并分别勾选上午、下午节次。
        </p>
      )}
      <p className="rule-group-slot-pattern-note">
        保存时会同时写入「允许课位」+「组合分布」；周课时仍从课时管理读取。
      </p>
    </div>
  );
}

function SpecificSlotEditor({
  value,
  weekdays,
  periods,
  onChange,
}: {
  value?: SpecificSlot[];
  weekdays: string[];
  periods: string[];
  onChange: (slots: SpecificSlot[]) => void;
}) {
  const current = new Map(
    (value || []).map((slot) => [slot.weekday, new Set(slot.periods)]),
  );
  const updateDay = (weekday: number, selected: string[]) => {
    const next = new Map(current);
    const nextPeriods = selected
      .map((item) => Number(item.match(/\d+/)?.[0]))
      .filter((period) => Number.isInteger(period));
    if (nextPeriods.length) next.set(weekday, new Set(nextPeriods));
    else next.delete(weekday);
    onChange(
      [...next.entries()]
        .sort(([left], [right]) => left - right)
        .map(([day, dayPeriods]) => ({
          weekday: day,
          periods: [...dayPeriods].sort((left, right) => left - right),
        })),
    );
  };
  return (
    <div className="rule-group-specific-slots">
      <div className="rule-group-specific-slots-head">
        <span>具体不可用课位</span>
        <small>按星期分别选择，避免把星期和节次错误地交叉组合。</small>
      </div>
      {weekdays.map((weekdayName) => {
        const weekday = WEEKDAY_OPTIONS.indexOf(weekdayName) + 1;
        const selected = [...(current.get(weekday) || [])].map(
          (period) => `第${period}节`,
        );
        return (
          <label key={weekdayName}>
            <span>{weekdayName}</span>
            <Select
              mode="multiple"
              maxTagCount="responsive"
              value={selected}
              onChange={(next: string[]) => updateDay(weekday, next)}
              options={periods.map((period) => ({
                value: period,
                label: period,
              }))}
              placeholder="请选择不可用节次"
            />
          </label>
        );
      })}
    </div>
  );
}
const RULE_KIND_BY_ACTION: Record<string, RuleKind> = {
  禁止排课: "禁排",
  禁止占用指定课位: "禁排",
  仅允许指定课位: "禁排",
  仅允许指定科目: "禁排",
  限定允许科目: "禁排",
  组合限制: "禁排",
  必须安排: "固定",
  固定到指定课位: "固定",
  固定关联: "固定",
  选择自习日: "固定",
  晚课日固定节次: "固定",
  节次课时下限: "课时",
  每日课节上限: "偏好",
  优先安排: "偏好",
  主科靠前: "偏好",
  空节补活动课: "偏好",
  尽量避开: "偏好",
  均衡分配: "偏好",
  保持连续: "连续",
  尽量连续: "连续",
  要求连堂: "连续",
  保持连堂: "连续",
  均衡分布: "偏好",
  优先相邻安排: "偏好",
  单双周配对: "配对",
  白天单双周对课: "配对",
  互斥排课: "配对",
  保持相邻: "配对",
};
const RULE_SCOPE_OPTIONS_BY_FAMILY: Record<RuleFamily, RuleScope[]> = {
  slot: ["全局", "课位", "学科", "教师", "班级"],
  distribution: ["学科", "班级", "教师"],
  teacher: ["教师"],
  class: ["班级"],
  combination: ["全局", "课位", "学科", "教师", "班级"],
};

/** 每日课时上限：可选教师，或按学科覆盖该学科全部任课教师。 */
const scopeOptionsForRule = (
  family: RuleFamily,
  code: SchedulingRuleCode,
): RuleScope[] => {
  if (code === "teacher_daily_limit" || code === "teacher_gap_free")
    return ["教师", "学科"];
  if (code === "slot_forbidden") return ["学科", "教师", "班级", "全局"];
  if (code === "subject_allowed_slots") return ["学科"];
  if (code === "slot_teacher_role_required") return ["全局"];
  if (code === "teacher_period_minimum") return ["教师"];
  if (code === "subject_consecutive" || code === "class_slot_pattern")
    return ["学科"];
  if (code === "teacher_consecutive") return ["教师"];
  if (code === "subject_daytime_parity_pair") return ["学科"];
  return RULE_SCOPE_OPTIONS_BY_FAMILY[family];
};
const WEEKDAY_ENUMS = WEEKDAY_OPTIONS.slice(0, 7);
const weekdaySelections = (value: string) => {
  if (!value || value === "未指定") return [];
  if (value === "全周") return [...WEEKDAY_ENUMS];
  if (value === "工作日" || value === "周一至周五")
    return WEEKDAY_ENUMS.slice(0, 5);
  if (value === "按学科配置") return [...WEEKDAY_ENUMS];
  const rangeMatch = value.match(/(周[一二三四五六日])至(周[一二三四五六日])/);
  const rangeValues = rangeMatch
    ? WEEKDAY_ENUMS.slice(
        WEEKDAY_ENUMS.indexOf(rangeMatch[1]),
        WEEKDAY_ENUMS.indexOf(rangeMatch[2]) + 1,
      )
    : [];
  const directValues = WEEKDAY_ENUMS.filter((day) => value.includes(day));
  return [...new Set([...rangeValues, ...directValues])];
};

const QUANTITY_DETAIL_OPTIONS = [
  { value: "none", label: "不设置目标", match: "不限定" },
  { value: "consecutive", label: "至少 1 天连堂", match: "至少 1 天连堂" },
  {
    value: "daily-limit",
    label: "每天尽量不超过 3 节",
    match: "每天尽量不超过 3 节",
  },
  {
    value: "morning-afternoon",
    label: "每班上午一节、下午一节",
    match: "每班上午一节、下午一节",
  },
];
const DISTRIBUTION_TARGET_OPTIONS_BY_FAMILY: Record<
  RuleFamily,
  Array<{ value: DistributionTarget; label: string }>
> = {
  slot: [{ value: "none", label: "不设置目标" }],
  distribution: [
    { value: "none", label: "不设置目标" },
    { value: "consecutive", label: "连堂：连续 2 节，每周至少 1 天" },
    {
      value: "morning-afternoon",
      label: "分布：每班上午、下午各一节（两种方向可选）",
    },
  ],
  teacher: [
    { value: "none", label: "不设置目标" },
    { value: "daily-limit", label: "负荷：每天最多 N 节" },
  ],
  class: [{ value: "none", label: "不设置目标" }],
  combination: [{ value: "none", label: "不设置目标" }],
};
const DISTRIBUTION_TARGET_LABELS: Record<DistributionTarget, string> = {
  none: "",
  consecutive: "连续 2 节、每周至少 1 天",
  "daily-limit": "每天最多 N 节",
  "morning-afternoon": "每班上午、下午各一节（两种方向可选）",
};

/** 教师每日课时上限（R04）：优先 distributionSpec，其次 quantity 文案，默认 3。 */
const teacherDailyLimitCap = (
  rule: Pick<GenericScheduleRule, "quantity" | "quantitySpec" | "distributionSpec">,
) =>
  Number(rule.distributionSpec?.maxLessonsPerDay) ||
  Number(rule.quantitySpec?.amount) ||
  Number(String(rule.quantity || "").match(/\d+/)?.[0]) ||
  3;

const formatTeacherDailyLimitQuantity = (amount: number) =>
  `每天最多 ${amount} 节`;
const QUANTITY_UNIT_OPTIONS: Array<{ value: QuantityUnit; label: string }> = [
  { value: "period", label: "课时" },
  { value: "section", label: "节" },
  { value: "per_class", label: "每班" },
  { value: "per_day", label: "每天" },
  { value: "unlimited", label: "不限" },
];
const quantityUnitCode = (unit: string): QuantityUnit =>
  QUANTITY_UNIT_OPTIONS.find(
    (option) => option.value === unit || option.label === unit,
  )?.value || "section";
const parseQuantity = (value: string, spec?: QuantitySpec) => {
  if (spec)
    return { amount: spec.amount, unit: spec.unit, detail: spec.distribution };
  const amountMatch = value.match(/\d+(?:\.\d+)?/);
  const detail =
    QUANTITY_DETAIL_OPTIONS.find((option) => value.includes(option.match))
      ?.value || "none";
  const unit = value.includes("课时")
    ? "课时"
    : value.includes("每班")
      ? "每班"
      : value.includes("每天")
        ? "每天"
        : value === "不限定"
          ? "不限"
          : "节";
  return {
    amount: amountMatch ? Number(amountMatch[0]) : undefined,
    unit: quantityUnitCode(unit),
    detail,
  };
};

/** 节次教师均衡（R17-02）每人上限：优先 quantitySpec，其次 quantity 文案，默认 2。 */
const slotTeacherBalanceCap = (
  rule: Pick<GenericScheduleRule, "quantity" | "quantitySpec">,
) =>
  Number(rule.quantitySpec?.amount) ||
  Number(String(rule.quantity || "").match(/\d+/)?.[0]) ||
  2;

const formatSlotTeacherBalanceQuantity = (amount: number) =>
  `每人最多 ${amount} 节`;

const slotTeacherBalancePeriodLabel = (period?: string) =>
  period && period !== UNRESOLVED_PERIOD ? period : "第5节";

const slotTeacherBalanceTitle = (period: string | undefined, amount: number) =>
  `${slotTeacherBalancePeriodLabel(period)}教师每周最多${amount}节`;

const slotTeacherBalanceNote = (period: string | undefined, amount: number) => {
  const periodLabel = slotTeacherBalancePeriodLabel(period);
  return `硬约束、白天课：全周（含周六）每名任课教师${periodLabel}最多 ${amount} 节，多出来的算违规。班主任本班第5节见 R17-01；班主任在他班当科任也计入这 ${amount} 节。生成时会尽量摊给不同老师。晚自习不管。`;
};
const buildRuleSummary = (
  rule: Pick<
    GenericScheduleRule,
    | "target"
    | "operator"
    | "weekday"
    | "period"
    | "cycle"
    | "quantity"
    | "quantitySpec"
    | "distributionSpec"
    | "distributionTarget"
    | "specificSlots"
    | "allowedSubjects"
    | "requiredTeacherRole"
    | "rule_code"
    | "id"
  >,
) => {
  const target = rule.target || "未指定对象";
  const time = rule.specificSlots?.length
    ? specificSlotSummary(rule.specificSlots)
    : [
        rule.weekday !== "未指定" ? rule.weekday : "",
        rule.period !== UNRESOLVED_PERIOD ? rule.period : "具体课位待配置",
      ]
        .filter(Boolean)
        .join("、");
  const cycle = rule.cycle === "每周" ? "" : `（${rule.cycle}）`;
  const actionText: Record<string, string> = {
    禁止排课: `${target}不得安排课程`,
    禁止占用指定课位: `${target}不得占用指定课位`,
    仅允许指定课位: `${target}仅允许安排在指定课位`,
    仅允许指定科目: `${target}仅允许安排指定科目${rule.allowedSubjects?.length ? `（${rule.allowedSubjects.join("、")}）` : ""}`,
    固定到指定课位: `${target}固定安排在指定课位`,
    必须安排: `${target}必须安排课程`,
    要求连堂: `${target}要求连堂`,
    保持连堂: `${target}保持连堂授课`,
    均衡分布:
      rule.rule_code === "class_slot_pattern" || rule.id === "R08-02"
        ? (() => {
            const pattern = resolveSlotPattern(
              rule.distributionSpec,
              rule.weekday,
              rule.period,
            );
            return `${target}只能排${weekdayLabelFromCodeList(pattern.weekdays)}的${periodLabelFromCodeList(pattern.periods)}，且每班上下午各一节（两种方向可选）`;
          })()
        : `${target}均衡分布授课`,
    每日课节上限: `${target}控制每日课节负荷`,
    主科靠前: `${target}尽量安排在靠前节次`,
    空节补活动课: `${target}优先排第8、9节，仅在会出现空节时补进前面`,
    优先安排: `${target}优先安排`,
    尽量避开: `${target}尽量避开指定课位`,
    保持连续: `${target}保持连续授课`,
    尽量连续: `${target}尽量连续授课`,
    均衡分配: `${target}均衡分配指定课位`,
    优先相邻安排: `${target}的晚课按班级顺序轮转，保持各班进度一致`,
    晚课日固定节次: `${target}有晚课的当天白天必须安排指定节次`,
    节次课时下限: `${target}全周在指定节次合计至少${
      Number(rule.quantitySpec?.amount) ||
      Number(String(rule.quantity || "").match(/\d+/)?.[0]) ||
      2
    }节`,
    组合限制: `${target}遵守组合限制`,
    单双周配对: `${target}按单双周配对安排`,
    互斥排课: `${target}遵守互斥排课限制`,
    保持相邻: `${target}保持相邻安排`,
    固定关联: `${target}保持固定关联`,
    选择自习日: `${target}在候选日期中选择自习日`,
  };
  const base =
    rule.requiredTeacherRole === "head_teacher" && rule.operator === "必须安排"
      ? `${target}必须由班主任负责`
      : actionText[rule.operator] || `${target}执行“${rule.operator}”`;
  const timeText = time ? `，时间范围为${time}` : "";
  const targetKey =
    rule.distributionSpec?.target ||
    (rule.distributionTarget as DistributionTarget | undefined) ||
    "none";
  const distributionText =
    targetKey === "consecutive"
      ? `，连堂要求为连续${rule.distributionSpec?.consecutiveLength || 2}节、每周至少${rule.distributionSpec?.minimumDays || 1}天`
      : targetKey === "daily-limit"
        ? `，附加目标为${formatTeacherDailyLimitQuantity(teacherDailyLimitCap(rule))}`
        : DISTRIBUTION_TARGET_LABELS[targetKey]
          ? `，附加目标为${DISTRIBUTION_TARGET_LABELS[targetKey]}`
          : "";
  const isSlotTeacherBalance =
    rule.rule_code === "slot_teacher_balance" || rule.id === "R17-02";
  const quantityText = isSlotTeacherBalance
    ? `，目标为${formatSlotTeacherBalanceQuantity(slotTeacherBalanceCap(rule))}`
    : "";
  return `${base}${timeText}${distributionText}${quantityText}${cycle}。`;
};

type RulePreviewMark = "blocked" | "allowed" | "fixed" | "preferred" | "scope";

const rulePreviewModel = (rule: GenericScheduleRule) => {
  const code = ruleCodeForRule(rule);
  const target = shortenTargetLabel(rule.target || "");
  const days = weekdaySelections(rule.weekday);
  const periods = periodSelections(rule.period);
  const isEvening = textMeansEvening(rule) || code === "subject_evening_parity_pair";
  const effectivePeriods = periods.length
    ? periods
    : code === "class_evening_self_study_day"
      ? ["第8节", "第9节"]
      : isEvening
        ? ["第10节"]
        : code === "subject_consecutive" || code === "teacher_consecutive" || code === "class_gap_free"
          ? PERIOD_ENUMS.slice(0, 7)
          : [];
  const effectiveDays = days.length ? days : WEEKDAY_ENUMS;
  let mark: RulePreviewMark = "scope";
  let headline = "这条规则会参与排课求解";
  let detail = "当前没有锁定具体课位，算法会按规则对象和作用范围处理。";

  if (
    code === "slot_forbidden" ||
    code === "teacher_forbidden_slots" ||
    (code === "class_allowed_subjects" && (rule.id === "R18-b" || rule.quantity === "不排课"))
  ) {
    mark = "blocked";
    headline = `${target}在指定课位不可排课`;
    detail = "网格中的红色单元表示会被排课算法排除的候选课位。";
  } else if (code === "subject_allowed_slots" || code === "class_allowed_subjects") {
    mark = "allowed";
    headline = `${target}只允许落在指定课位`;
    detail = rule.allowedSubjects?.length
      ? `如果这些课位安排课程，只能使用：${rule.allowedSubjects.join("、")}。`
      : "只有高亮课位会进入候选集合，未高亮课位不会安排该对象。";
  } else if (code === "slot_teacher_role_required" || rule.operator === "固定到指定课位" || rule.operator === "必须安排") {
    mark = "fixed";
    headline = `${target}必须在指定课位完成安排`;
    detail = "网格中的蓝色单元是固定/必须满足的课位，排课时会优先保护。";
  } else if (code === "subject_consecutive") {
    mark = "preferred";
    const length = rule.distributionSpec?.consecutiveLength || 2;
    const count = rule.distributionSpec?.minimumDays || 1;
    headline = `${target}每周至少 ${count} 天形成连续 ${length} 节`;
    detail = "橙色区域表示连堂作用范围；具体从哪一组连续节次开始由排课算法结合其它约束决定。";
  } else if (code === "teacher_consecutive") {
    mark = "preferred";
    const length = rule.distributionSpec?.consecutiveLength || 2;
    const count = rule.distributionSpec?.minimumDays || 1;
    const mode = rule.distributionSpec?.teacherClassMode === "cross_class" ? "跨班" : "同一班";
    headline = `${target}${mode}连堂：每周至少 ${count} 天连续 ${length} 节`;
    detail = "连续课节按教师的全部任教班级统计；跨班模式要求连续课节至少覆盖两个班。";
  } else if (code === "teacher_daily_limit" || code === "teacher_gap_free") {
    mark = "preferred";
    headline = `${target}工作日每天最多 ${teacherDailyLimitCap(rule)} 节，并保持白天课位连续`;
    detail = "这是教师负荷与空节控制规则，不会把某一门课钉死在单个课位。";
  } else if (code === "subject_daytime_parity_pair" || code === "subject_evening_parity_pair") {
    mark = "fixed";
    headline = `${target}按单双周在同一课位配对`;
    detail = "同一网格位置由单周/双周分别承载不同学科，避免两组课位错开。";
  } else if (code === "class_gap_free") {
    mark = "fixed";
    headline = `${target}白天第 1～7 节尽量不留空堂`;
    detail = "网格表示白天必排范围；第 8、9 节自习位不计入这条规则。";
  } else if (code === "subject_prefer_early_periods") {
    mark = "preferred";
    headline = `${target}优先安排在靠前节次`;
    detail = `允许最多 ${rule.maxOutsidePreferred ?? rule.quantitySpec?.amount ?? 0} 节落在偏好节次之外。`;
  } else if (code === "subject_gap_fill_late_periods") {
    mark = "preferred";
    headline = `${target}优先填补第 8、9 节活动课位`;
    detail = "只有前面出现空节时，才会把活动课补进第 1～7 节。";
  } else if (code === "class_evening_self_study_day") {
    mark = "allowed";
    headline = `${target}从候选日期中选择 ${rule.choiceCount || 1} 天保持第 8、9 节自习`;
    detail = "高亮的是可选自习日，不代表这些日期都会被排成自习。";
  } else if (code === "teacher_period_minimum") {
    mark = "fixed";
    headline = `${target}在选定节次中全周至少安排 ${rule.quantitySpec?.amount || 2} 节`;
    detail = "这是全周累计下限，不要求集中在同一天。";
  } else if (code === "slot_teacher_balance") {
    mark = "preferred";
    headline = `指定节次由不同教师均衡分担`;
    detail = `每名教师每周最多承担 ${slotTeacherBalanceCap(rule)} 节，不会锁定某一名教师。`;
  }

  return { mark, headline, detail, days: effectiveDays, periods: effectivePeriods, isEvening };
};

function RuleImpactPreview({
  rule,
  compact = false,
  gridConfig,
}: {
  rule: GenericScheduleRule;
  compact?: boolean;
  gridConfig?: SchedulingGridConfig;
}) {
  const model = rulePreviewModel(rule);
  const daySet = new Set(model.days);
  const periodSet = new Set(model.periods);
  const parityPair = ["subject_daytime_parity_pair", "subject_evening_parity_pair"].includes(
    ruleCodeForRule(rule),
  ) || rule.cycle === "单周 / 双周";
  const hasSavedGrid = gridConfig?.configured === true;
  const configuredDailyPeriods = hasSavedGrid
    ? gridConfig?.daily_periods || []
    : [9, 9, 9, 9, 9, 9, 9];
  const configuredDays = WEEKDAY_ENUMS.filter((_, index) => configuredDailyPeriods[index] > 0);
  const daytimePeriodCount = Math.max(1, ...configuredDailyPeriods);
  const eveningPeriodCount = hasSavedGrid && gridConfig?.enable_evening
    ? Math.max(...(gridConfig.evening_daily_periods_odd || []), ...(gridConfig.evening_daily_periods_even || []), 0)
    : 0;
  const previewDays = configuredDays.length ? configuredDays : WEEKDAY_ENUMS;
  const configuredPeriodCount = model.isEvening
    ? daytimePeriodCount + eveningPeriodCount
    : daytimePeriodCount;
  const basePeriods = parityPair && model.periods.length === 0
    ? (model.isEvening ? [`第${Math.max(daytimePeriodCount + 1, 10)}节`] : PERIOD_ENUMS.slice(0, configuredPeriodCount))
    : [...new Set([
        ...PERIOD_ENUMS.slice(0, configuredPeriodCount),
        ...model.periods,
      ])];
  const previewRows = parityPair
    ? basePeriods.flatMap((period) => [
        { label: `${model.isEvening && model.periods.length === 0 ? "晚自习" : period} · 单周`, period, parity: "odd" as const },
        { label: `${model.isEvening && model.periods.length === 0 ? "晚自习" : period} · 双周`, period, parity: "even" as const },
      ])
    : basePeriods.map((period) => ({ label: period, period, parity: null }));
  const markText: Record<RulePreviewMark, string> = {
    blocked: "禁",
    allowed: "可",
    fixed: "定",
    preferred: "优",
    scope: "·",
  };
  return (
    <div className={`rule-group-impact-preview${compact ? " is-compact" : ""}`}>
      <div className="rule-group-impact-head">
        <div>
          <span className="rule-group-field-label">规则影响预览</span>
          <strong>{model.headline}</strong>
        </div>
        <Tag color={model.mark === "blocked" ? "red" : model.mark === "fixed" ? "blue" : "gold"}>
          {rule.priority === "hard" ? "硬约束" : "软目标"}
        </Tag>
      </div>
      <p className="rule-group-impact-detail">{model.detail}</p>
      {!compact && (
        <div className="rule-group-impact-grid" aria-label="规则作用课位预览">
          <div className="rule-group-impact-grid-row is-head">
            <span>节次</span>
            {previewDays.map((day) => <span key={day}>{day}</span>)}
          </div>
          {previewRows.map((row) => (
            <div className="rule-group-impact-grid-row" key={row.label}>
              <span>{row.label}</span>
              {previewDays.map((day) => {
                const active = daySet.has(day) && periodSet.has(row.period);
                return (
                  <span
                    key={`${day}-${row.label}`}
                    className={`rule-group-impact-cell ${active ? `is-${model.mark}` : ""}`}
                  >
                    {active ? (row.parity === "odd" ? "单" : row.parity === "even" ? "双" : markText[model.mark]) : ""}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      )}
      <small>配置影响预览 · 保存后参与排课；最终课表仍需运行排课算法生成。</small>
    </div>
  );
}

function DistributionTargetEditor({
  family,
  spec,
  onChange,
}: {
  family: RuleFamily;
  spec?: DistributionSpec;
  onChange: (spec: DistributionSpec) => void;
}) {
  const target = spec?.target || "none";
  const updateTarget = (nextTarget: DistributionTarget) => {
    onChange({
      target: nextTarget,
      consecutiveLength:
        nextTarget === "consecutive" ? spec?.consecutiveLength || 2 : undefined,
      minimumDays:
        nextTarget === "consecutive" ? spec?.minimumDays || 1 : undefined,
      maxLessonsPerDay:
        nextTarget === "daily-limit" ? spec?.maxLessonsPerDay || 3 : undefined,
      patternMode:
        nextTarget === "morning-afternoon"
          ? spec?.patternMode || "either-direction"
          : undefined,
    });
  };
  const updateConsecutive = (
    key: "consecutiveLength" | "minimumDays",
    value: number | null,
  ) => {
    onChange({
      ...spec,
      target,
      [key]: value || undefined,
    } as DistributionSpec);
  };
  const updateDailyLimit = (value: number | null) => {
    onChange({
      ...spec,
      target: "daily-limit",
      maxLessonsPerDay: Math.max(1, Math.min(9, Number(value) || 3)),
    });
  };
  const familyOptions = DISTRIBUTION_TARGET_OPTIONS_BY_FAMILY[family] || [
    { value: "none" as DistributionTarget, label: "不设置目标" },
  ];
  const options = familyOptions.some((item) => item.value === target)
    ? familyOptions
    : [
        ...familyOptions,
        {
          value: target,
          label: DISTRIBUTION_TARGET_LABELS[target] || target,
        },
      ];
  return (
    <div className="rule-group-distribution-editor">
      <div className="rule-group-distribution-row">
        <span>目标</span>
        <Select value={target} options={options} onChange={updateTarget} />
      </div>
      {target === "morning-afternoon" && (
        <div className="rule-group-pattern-preview">
          <strong>允许的课位组合</strong>
          <span>方案一：周二上午 + 周四下午</span>
          <span>方案二：周二下午 + 周四上午</span>
          <small>
            上午为第3、4节，下午为第6、7节；算法满足其中一个方案即可。
          </small>
        </div>
      )}
      {target === "consecutive" && (
        <div className="rule-group-distribution-grid">
          <label>
            <span>连续长度</span>
            <Space.Compact block>
              <InputNumber
                min={2}
                max={9}
                value={spec?.consecutiveLength || 2}
                onChange={(value) =>
                  updateConsecutive("consecutiveLength", value)
                }
              />
              <span className="rule-group-unit-suffix">节</span>
            </Space.Compact>
          </label>
          <label>
            <span>每周至少</span>
            <Space.Compact block>
              <InputNumber
                min={1}
                max={7}
                value={spec?.minimumDays || 1}
                onChange={(value) => updateConsecutive("minimumDays", value)}
              />
              <span className="rule-group-unit-suffix">天</span>
            </Space.Compact>
          </label>
        </div>
      )}
      {target === "daily-limit" && (
        <div className="rule-group-distribution-grid">
          <label>
            <span>每天最多</span>
            <Space.Compact block>
              <InputNumber
                min={1}
                max={9}
                value={spec?.maxLessonsPerDay || 3}
                onChange={updateDailyLimit}
              />
              <span className="rule-group-unit-suffix">节</span>
            </Space.Compact>
          </label>
        </div>
      )}
    </div>
  );
}

const normalizeAmbiguousRules = (rules: GenericScheduleRule[]) =>
  rules.map((rule) => {
    const parsedQuantity = parseQuantity(rule.quantity, rule.quantitySpec);
    const quantitySpec = rule.quantitySpec || {
      amount: parsedQuantity.amount,
      unit: parsedQuantity.unit,
      distribution: parsedQuantity.detail,
    };
    const family =
      (rule.family as string) === "quantity"
        ? "distribution"
        : rule.family || familyForRule(rule);
    const distributionTarget = (rule.distributionSpec?.target ||
      rule.distributionTarget ||
      parsedQuantity.detail ||
      "none") as DistributionTarget;
    const distributionSpec: DistributionSpec = rule.distributionSpec || {
      target: distributionTarget,
      consecutiveLength: distributionTarget === "consecutive" ? 2 : undefined,
      minimumDays: distributionTarget === "consecutive" ? 1 : undefined,
      patternMode:
        distributionTarget === "morning-afternoon"
          ? "either-direction"
          : undefined,
    };
    const operator =
      (
        {
          限定课位: "仅允许指定课位",
          禁止安排指定节次: "禁止占用指定课位",
          固定课位: "固定到指定课位",
          限定允许科目: "仅允许指定科目",
        } as Record<string, string>
      )[rule.operator] || rule.operator;
    let normalizedOperator = operator;
    if (
      rule.id === "R19-03" ||
      rule.rule_code === "class_evening_self_study_day"
    ) {
      normalizedOperator = "选择自习日";
    }
    if (family === "distribution") {
      if (normalizedOperator === "每周课时")
        normalizedOperator =
          distributionTarget === "consecutive" ? "要求连堂" : "均衡分布";
      if (normalizedOperator === "必须满足")
        normalizedOperator =
          distributionTarget === "consecutive" ? "要求连堂" : "均衡分布";
    }
    const normalizedKind =
      RULE_KIND_BY_ACTION[normalizedOperator] ||
      (rule.kind === "课时" ? "偏好" : rule.kind);
    const allowedSubjects = rule.allowedSubjects?.length
      ? rule.allowedSubjects
      : undefined;
    const isTypedEveningRule =
      rule.id === "R15" ||
      rule.rule_code === "teacher_multi_class_evening_adjacent";
    const needsPeriodNormalization =
      /早课|白天课|晚课/.test(rule.period) && !isTypedEveningRule;
    const needsSlotConfiguration =
      needsPeriodNormalization && family !== "distribution";
    const needsQuantityConfiguration = rule.quantity.includes("晚课");
    const needsActionNormalization = rule.operator === "禁止安排晚课";
    if (
      !needsPeriodNormalization &&
      !needsQuantityConfiguration &&
      !needsActionNormalization &&
      normalizedOperator === rule.operator &&
      family === rule.family &&
      allowedSubjects === rule.allowedSubjects
    ) {
      return {
        ...rule,
        family,
        quantitySpec,
        distributionTarget,
        distributionSpec,
        kind: normalizedKind,
      };
    }
    const quantity = needsQuantityConfiguration
      ? /^晚课\s*\d+\s*节$/.test(rule.quantity)
        ? rule.quantity.replace("晚课", "").trim()
        : "不限定"
      : rule.quantity;
    return {
      ...rule,
      family,
      operator: needsActionNormalization
        ? "禁止占用指定课位"
        : normalizedOperator,
      kind: needsActionNormalization ? "禁排" : normalizedKind,
      period: needsPeriodNormalization ? UNRESOLVED_PERIOD : rule.period,
      quantity,
      quantitySpec,
      distributionTarget,
      distributionSpec,
      allowedSubjects,
      status: (needsSlotConfiguration || needsActionNormalization
        ? "unresolved"
        : rule.status) as RuleStatus,
      note: needsSlotConfiguration
        ? `${rule.note} 具体课位需先在课时管理中配置后，才能参与自动排课。`
        : rule.note,
    };
  });

const defaultGroup = (): RuleGroup => ({
  id: "grade-1",
  name: "高一组排课规则",
  grade_id: null,
  scope: "高一年级 · 10 个班",
  term: "2026–2027 · 第 1 学期",
  rules: normalizeAmbiguousRules(DEFAULT_RULES),
});

const migrateLegacyGroup = (group: RuleGroup): RuleGroup => {
  const hasLegacyPrepRule = group.rules.some(
    (rule) => rule.id === "R01" && rule.title === "各科备课时段禁排",
  );
  const legacySportsRule = group.rules.find((rule) => rule.id === "R08");
  const legacyBalanceRule = group.rules.find((rule) => rule.id === "R17");
  const legacyClassRule = group.rules.find((rule) => rule.id === "R19");
  const legacyMaoRule = group.rules.find(
    (rule) => rule.id === "R12" && !rule.specificSlots,
  );
  const splitPrepRules = DEFAULT_RULES.filter((rule) =>
    rule.id.startsWith("R01-"),
  );
  const splitSportsRules = DEFAULT_RULES.filter((rule) =>
    rule.id.startsWith("R08-"),
  );
  const splitBalanceRules = DEFAULT_RULES.filter((rule) =>
    rule.id.startsWith("R17-"),
  );
  const splitClassRules = DEFAULT_RULES.filter((rule) =>
    rule.id.startsWith("R19-"),
  );
  const structuredMaoRule = DEFAULT_RULES.find((rule) => rule.id === "R12");
  let rules =
    hasLegacyPrepRule && splitPrepRules.length
      ? [...splitPrepRules, ...group.rules.filter((rule) => rule.id !== "R01")]
      : group.rules;
  if (legacySportsRule && splitSportsRules.length) {
    const sportsIndex = rules.findIndex((rule) => rule.id === "R08");
    rules =
      sportsIndex < 0
        ? [...rules, ...splitSportsRules]
        : [
            ...rules.slice(0, sportsIndex),
            ...splitSportsRules,
            ...rules.slice(sportsIndex + 1),
          ];
  }
  // 学科上下午分布：允许课位 + 组合分布合并为一条展示（R08-02）
  if (rules.some((rule) => rule.id === "R08-02")) {
    const bundled = DEFAULT_RULES.find((rule) => rule.id === "R08-02");
    rules = rules
      .filter((rule) => rule.id !== "R08-01")
      .map((rule) =>
        rule.id === "R08-02" && bundled
          ? {
              ...rule,
              title: bundled.title,
              note: bundled.note,
              rule_code: "class_slot_pattern",
              distributionSpec: bundled.distributionSpec,
              weekday: bundled.weekday,
              period: bundled.period,
            }
          : rule,
      );
  }
  if (legacyBalanceRule && splitBalanceRules.length) {
    const balanceIndex = rules.findIndex((rule) => rule.id === "R17");
    rules =
      balanceIndex < 0
        ? [...rules, ...splitBalanceRules]
        : [
            ...rules.slice(0, balanceIndex),
            ...splitBalanceRules,
            ...rules.slice(balanceIndex + 1),
          ];
  }
  if (legacyClassRule && splitClassRules.length) {
    const classIndex = rules.findIndex((rule) => rule.id === "R19");
    rules =
      classIndex < 0
        ? [...rules, ...splitClassRules]
        : [
            ...rules.slice(0, classIndex),
            ...splitClassRules,
            ...rules.slice(classIndex + 1),
          ];
  }
  if (legacyMaoRule && structuredMaoRule) {
    const maoIndex = rules.findIndex((rule) => rule.id === "R12");
    rules =
      maoIndex < 0
        ? [...rules, structuredMaoRule]
        : [
            ...rules.slice(0, maoIndex),
            structuredMaoRule,
            ...rules.slice(maoIndex + 1),
          ];
  }
  const legacyAdjacentRule = rules.find(
    (rule) => rule.id === "R15" && rule.operator !== "优先相邻安排",
  );
  const structuredAdjacentRule = DEFAULT_RULES.find(
    (rule) => rule.id === "R15",
  );
  if (legacyAdjacentRule && structuredAdjacentRule) {
    const adjacentIndex = rules.findIndex((rule) => rule.id === "R15");
    rules =
      adjacentIndex < 0
        ? [...rules, structuredAdjacentRule]
        : [
            ...rules.slice(0, adjacentIndex),
            structuredAdjacentRule,
            ...rules.slice(adjacentIndex + 1),
          ];
  }
  // R04-load / R04-continuity 是保存时拆出的后端条目；工作台只展示一条 R04。
  if (
    rules.some(
      (rule) => rule.id === "R04-load" || rule.id === "R04-continuity",
    )
  ) {
    const template = DEFAULT_RULES.find((rule) => rule.id === "R04");
    if (template) {
      const load = rules.find((rule) => rule.id === "R04-load");
      const dailyCap = load
        ? teacherDailyLimitCap(load)
        : teacherDailyLimitCap(template);
      const folded = makeRule({
        ...template,
        family: "teacher",
        enabled: load?.enabled ?? template.enabled,
        priority: load?.priority ?? template.priority,
        title: template.title,
        scope: "学科",
        target: template.target,
        rule_code: "teacher_daily_limit",
        quantity: formatTeacherDailyLimitQuantity(dailyCap),
        quantitySpec: {
          amount: dailyCap,
          unit: "per_day",
          distribution: "daily-limit",
        },
        distributionSpec: {
          target: "daily-limit",
          maxLessonsPerDay: dailyCap,
        },
        status: "pass",
      });
      const without = rules.filter(
        (rule) =>
          rule.id !== "R04" &&
          rule.id !== "R04-load" &&
          rule.id !== "R04-continuity" &&
          // 已废弃的独立「教师无空节」不再占位
          rule.id !== "R03" &&
          rule.id !== "R11" &&
          rule.rule_code !== "teacher_gap_free",
      );
      const afterR02 = without.findIndex((rule) => rule.id === "R02");
      rules =
        afterR02 >= 0
          ? [
              ...without.slice(0, afterR02 + 1),
              folded,
              ...without.slice(afterR02 + 1),
            ]
          : [folded, ...without];
    }
  }
  rules = rules.map((rule) =>
    rule.id === "R02"
      ? {
          ...rule,
          category: "global" as RuleCategory,
          family: "slot" as RuleFamily,
          scope: "全局" as RuleScope,
          target: "全年级",
          kind: "固定" as RuleKind,
          operator: "必须安排",
          relation: "无",
          weekday: rule.weekday && rule.weekday !== "未指定" ? rule.weekday : "周六",
          period: /^第\d+节$/.test(rule.period) ? rule.period : "第10节",
          requiredTeacherRole: "head_teacher" as const,
          rule_code: "slot_teacher_role_required" as SchedulingRuleCode,
          title:
            rule.title === "周六晚课安排班主任" || rule.title === "周六第9节安排班主任"
              ? "周六晚自习安排班主任"
              : rule.title,
          note: "勾选的星期和节次，每个班必须由本班班主任负责。",
        }
      : rule,
  );
  rules = rules.map((rule) =>
    rule.id === "R17-01"
      ? {
          ...rule,
          category: "teacher" as RuleCategory,
          family: "teacher" as RuleFamily,
          scope: "教师" as RuleScope,
          target: "班主任",
          kind: "禁排" as RuleKind,
          operator: "禁止排课",
          relation: "无",
          weekday: "全周",
          period: "第5节",
          rule_code: "teacher_forbidden_slots" as SchedulingRuleCode,
          title: "本班第五节不排班主任",
          note: "硬约束、白天课：班主任只禁自己当班主任的那个班的第5节（含周六）；在其它班当科任可以排第5节，用来分担科任第5节压力。晚自习不管。",
        }
      : rule,
  );
  rules = rules.map((rule) =>
    rule.id === "R05" && rule.title === "数学连堂规则"
      ? {
          ...rule,
          title: "学科连堂",
          note: "所选学科每周至少有1天安排连续2节，周课时数量以课时管理配置为准。",
        }
      : rule,
  );
  rules = rules.map((rule) =>
    rule.id === "R22" && rule.title === "物理历史晚课单双周配对"
      ? {
          ...rule,
          title: "学科晚课单双周配对",
          note: "同一晚课格内的两组学科按单双周配对；单周/双周对应关系可按配置调整。",
        }
      : rule,
  );
  rules = rules.map((rule) => {
    if (rule.id !== "R17-02") return rule;
    const amount = slotTeacherBalanceCap(rule);
    const period = rule.period && rule.period !== UNRESOLVED_PERIOD
      ? rule.period
      : "第5节";
    return {
      ...rule,
      category: "teacher" as RuleCategory,
      family: "teacher" as RuleFamily,
      scope: "教师" as RuleScope,
      target: rule.target || "科任教师",
      kind: "固定" as RuleKind,
      operator: "均衡分配",
      relation: "无",
      weekday: rule.weekday || "全周",
      period,
      quantity: formatSlotTeacherBalanceQuantity(amount),
      quantitySpec: {
        amount,
        unit: "section" as QuantityUnit,
        distribution: rule.quantitySpec?.distribution || "none",
      },
      rule_code: "slot_teacher_balance" as SchedulingRuleCode,
      title: slotTeacherBalanceTitle(period, amount),
      note: slotTeacherBalanceNote(period, amount),
    };
  });
  const legacyHuangCombo = rules.find(
    (rule) =>
      rule.id === "R10" &&
      (rule.operator === "组合限制" ||
        /有晚课当天排第7节，另外2课时/.test(rule.note || "")),
  );
  const structuredHuangRules = DEFAULT_RULES.filter((rule) =>
    ["R10", "R10-b", "R10-c"].includes(rule.id),
  );
  // 仅当组内已有 R10 时，才补齐/拆分 R10-b、R10-c。
  // 空组或其它年级组绝不能被塞进高一默认的黄丽娟三条规则。
  if (legacyHuangCombo && structuredHuangRules.length === 3) {
    const huangIndex = rules.findIndex((rule) => rule.id === "R10");
    const withoutHuang = rules.filter(
      (rule) => !["R10", "R10-b", "R10-c"].includes(rule.id),
    );
    rules =
      huangIndex < 0
        ? withoutHuang
        : [
            ...withoutHuang.slice(0, huangIndex),
            ...structuredHuangRules,
            ...withoutHuang.slice(huangIndex),
          ];
  } else if (
    rules.some((rule) => rule.id === "R10") &&
    !rules.some((rule) => rule.id === "R10-b")
  ) {
    const insertAt = rules.findIndex((rule) => rule.id === "R10");
    const extras = structuredHuangRules.filter(
      (rule) =>
        rule.id !== "R10" &&
        !rules.some((existing) => existing.id === rule.id),
    );
    if (extras.length && insertAt >= 0) {
      rules = [
        ...rules.slice(0, insertAt + 1),
        ...extras,
        ...rules.slice(insertAt + 1),
      ];
    }
  }
  // 丢掉已废弃的独立教师无空节（R03 / R11 等）；R04 工作日无空节仍由 -continuity 写入后端
  rules = rules.filter(
    (rule) =>
      rule.id !== "R03" &&
      rule.id !== "R11" &&
      !(
        rule.rule_code === "teacher_gap_free" &&
        rule.id !== "R04-continuity" &&
        !String(rule.id).endsWith("-continuity")
      ),
  );
  return { ...group, rules: normalizeAmbiguousRules(rules) };
};

const loadGroup = (): RuleGroup => defaultGroup();

const blankRule = (id: string): GenericScheduleRule =>
  makeRule({
    id,
    category: "global",
    scope: "课位",
    family: "slot",
    target: "",
    kind: "固定",
    operator: "必须安排",
    relation: "无",
    weekday: "未指定",
    period: UNRESOLVED_PERIOD,
    cycle: "每周",
    quantity: "不限定",
    priority: "soft",
    status: "unresolved",
    title: "新的通用排课规则",
    note: "",
  });

const ruleTemplateForRule = (
  rule: GenericScheduleRule,
): RuleTemplate | undefined => {
  const code = rule.rule_code || ruleCodeForRule(rule);
  return code === "manual_review" ? undefined : RULE_TEMPLATE_MAP.get(code);
};

const weekdayCodes = (value: string) =>
  weekdaySelections(value)
    .map((day) => WEEKDAY_OPTIONS.indexOf(day) + 1)
    .filter((day) => day > 0);
const periodCodes = (value: string) =>
  periodSelections(value)
    .map((item) => Number(item.match(/\d+/)?.[0]))
    .filter((period) => Number.isInteger(period));

const stripNegatedEvening = (text: string) =>
  text.replace(/不管晚自习|晚自习不管|不论晚自习|不含晚自习|晚自习不计/g, "");

const textMeansEvening = (rule: GenericScheduleRule) => {
  const core = `${rule.period}${rule.title}${rule.operator}`;
  if (/晚课|晚自习/.test(core)) return true;
  return /晚课|晚自习/.test(stripNegatedEvening(rule.note || ""));
};
const normalizeTargetName = (value: string) =>
  value.replace(/[（）]/g, (char) => (char === "（" ? "(" : ")")).trim();

const targetTypeForRule = (
  rule: GenericScheduleRule,
): "global" | "slot" | "subject" | "teacher" | "class" => {
  if (rule.scope === "学科") return "subject";
  if (rule.scope === "教师") return "teacher";
  if (rule.scope === "班级") return "class";
  if (rule.scope === "课位") return "slot";
  return "global";
};

const slotTargetId = (target: string) => {
  const match = target.match(/^周([一二三四五六日])\s*[·•]\s*第(\d+)节$/);
  if (!match) return undefined;
  const weekday = WEEKDAY_OPTIONS.indexOf(`周${match[1]}`) + 1;
  const period = Number(match[2]);
  return weekday > 0 && period > 0 ? weekday * 100 + period : undefined;
};

const R04_SUBJECT_TARGET =
  "语文 / 数学 / 英语 / 物理 / 化学 / 生物 / 政治 / 历史 / 地理 / 音乐 / 美术 / 心理";
const r04NoteSubject = (amount = 3) =>
  `学科模式：勾选学科后，这些学科的任课老师都受约束——工作日每天最多 ${amount} 节，白天 1～7 节不能空节。一般不要勾体育。`;
const r04NoteTeacher = (amount = 3) =>
  `教师模式：直接勾选老师（或选「多班教师」）。只有名单里的人受约束——工作日每天最多 ${amount} 节，白天 1～7 节不能空节。`;

/** 多选对象名称：R04 / 课位禁排等按作用对象放开多选。 */
const isMultiNameTargetRule = (rule: GenericScheduleRule) => {
  if (rule.id === "R04" || rule.id.startsWith("R04-")) {
    return rule.scope === "学科" || rule.scope === "教师";
  }
  const code = ruleCodeForRule(rule);
  if (code === "slot_forbidden") {
    return (
      rule.scope === "学科" ||
      rule.scope === "教师" ||
      rule.scope === "班级"
    );
  }
  if (
    code === "subject_allowed_slots" ||
    code === "subject_consecutive" ||
    code === "class_slot_pattern" ||
    code === "subject_evening_parity_pair"
  ) {
    return rule.scope === "学科";
  }
  if (code === "teacher_consecutive") return rule.scope === "教师";
  if (
    code === "teacher_period_minimum" ||
    code === "teacher_multi_class_evening_adjacent" ||
    code === "teacher_evening_daytime_link" ||
    code === "teacher_preferred_weekdays"
  ) {
    return rule.scope === "教师";
  }
  if (rule.scope === "教师") return true;
  return (
    rule.scope === "学科" &&
    (rule.id === "R22" ||
      code === "teacher_daily_limit" ||
      code === "teacher_gap_free" ||
      code === "subject_prefer_early_periods" ||
      code === "subject_gap_fill_late_periods")
  );
};

const resolveTargetIds = (
  rule: GenericScheduleRule,
  resources?: SchedulingResources,
) => {
  if (!resources) return [];
  const target = normalizeTargetName(rule.target);
  const type = targetTypeForRule(rule);
  if (type === "subject") {
    const names = target.split(/\s*[\/、]\s*/);
    return resources.subjects
      .filter((item) => names.includes(item.name))
      .map((item) => item.id);
  }
  if (type === "class") {
    if (/全年级/.test(target)) {
      return resources.classes.map((item) => item.id);
    }
    const names = target.split(/\s*[\/、]\s*/);
    return resources.classes
      .filter((item) => names.includes(normalizeTargetName(item.name)))
      .map((item) => item.id);
  }
  if (type === "teacher") {
    if (target === "多班教师") {
      const counts = new Map<number, Set<number>>();
      resources.assignments.forEach((item) => {
        if (item.teacher_id == null) return;
        const classes = counts.get(item.teacher_id) || new Set<number>();
        classes.add(item.class_id);
        counts.set(item.teacher_id, classes);
      });
      return [...counts]
        .filter(([, classes]) => classes.size > 1)
        .map(([teacherId]) => teacherId);
    }
    if (target === "班主任")
      return [
        ...new Set(
          resources.classes
            .map((item) => item.head_teacher_id)
            .filter((id): id is number => id != null),
        ),
      ];
    if (target === "科任教师") return resources.teachers.map((item) => item.id);
    const names = target.split(/\s*[\/、]\s*/);
    return resources.teachers
      .filter((item) => names.includes(item.name))
      .map((item) => item.id);
  }
  if (type === "slot") {
    const id = slotTargetId(target);
    return id ? [id] : [];
  }
  return [];
};

const canonicalRule = (
  rule: GenericScheduleRule,
  resources?: SchedulingResources,
): SchedulingRuleDefinition[] => {
  const originalCode = rule.rule_code || ruleCodeForRule(rule);
  const ids = resolveTargetIds(rule, resources);
  const targetType = targetTypeForRule(rule);
  const fallback = (id = rule.id): SchedulingRuleDefinition => ({
    id,
    title: rule.title,
    code: "manual_review",
    enabled: rule.enabled,
    priority: rule.priority,
    target: { type: "global", ids: [] },
    weekdays: weekdayCodes(rule.weekday),
    periods: periodCodes(rule.period),
    period_scope:
      /晚课/.test(rule.period) || originalCode === "slot_teacher_role_required"
        ? "evening"
        : "regular",
    week_parity: "all",
    params: { source_operator: rule.operator },
  });
  if (
    originalCode === "manual_review" ||
    (targetType !== "global" && !ids.length)
  )
    return [fallback()];
  const base = {
    title: rule.title,
    enabled: rule.enabled,
    priority: rule.priority,
    target: { type: targetType, ids },
    weekdays: weekdayCodes(rule.weekday),
    periods: periodCodes(rule.period),
    period_scope:
      /晚课/.test(rule.period) || originalCode === "slot_teacher_role_required"
        ? ("evening" as const)
        : ("regular" as const),
    week_parity: "all" as const,
  };
  if (originalCode === "subject_consecutive" || originalCode === "teacher_consecutive") {
    if ((originalCode === "subject_consecutive" && targetType !== "subject") ||
      (originalCode === "teacher_consecutive" && targetType !== "teacher") || !ids.length) return [fallback()];
    const blockLength = rule.distributionSpec?.consecutiveLength || 2;
    const minimumDays = rule.distributionSpec?.minimumDays || 1;
    if (blockLength < 2 || minimumDays < 1) return [fallback()];
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        // 连堂按整天白天节次判断，不按用户误选的零散节次过滤
        periods: [],
        period_scope: "regular",
        params: {
          minimum_block_length: blockLength,
          minimum_days: minimumDays,
          ...(originalCode === "teacher_consecutive"
            ? { class_mode: rule.distributionSpec?.teacherClassMode || "same_class" }
            : {}),
        },
      },
    ];
  }
  if (originalCode === "slot_forbidden") {
    const weekdays = weekdayCodes(rule.weekday);
    const periods = periodCodes(rule.period);
    if ((targetType !== "global" && !ids.length) || !weekdays.length || !periods.length) {
      return [fallback()];
    }
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        weekdays,
        periods,
        period_scope: "regular",
        params: { source_operator: rule.operator },
      },
    ];
  }
  if (originalCode === "class_slot_pattern") {
    if (targetType !== "subject" || !ids.length) return [fallback()];
    const pattern = resolveSlotPattern(
      rule.distributionSpec,
      rule.weekday,
      rule.period,
    );
    const weekdays = pattern.weekdays;
    const periods = pattern.periods;
    const alternatives = buildEitherDirectionAlternatives(
      pattern.weekdays,
      pattern.morning,
      pattern.afternoon,
    );
    if (weekdays.length !== 2 || !pattern.morning.length || !pattern.afternoon.length || !alternatives.length) {
      return [fallback()];
    }
    // 一条 UI 规则 → 允许课位 + 组合分布；多学科时按学科拆开
    return ids.flatMap((subjectId, index) => {
      const patternId =
        index === 0 ? rule.id : `${rule.id}-s${subjectId}`;
      const allowId = `${rule.id}-allow-${subjectId}`;
      const target = { type: "subject" as const, ids: [subjectId] };
      return [
        {
          ...base,
          id: patternId,
          code: originalCode,
          target,
          weekdays,
          periods,
          period_scope: "regular" as const,
          params: {
            match_mode: "exact",
            alternatives,
            bundled_with: allowId,
          },
        },
        {
          ...base,
          id: allowId,
          code: "subject_allowed_slots" as const,
          target,
          weekdays,
          periods,
          period_scope: "regular" as const,
          params: {
            bundled_from: patternId,
            source_operator: "均衡分布",
          },
        },
      ];
    });
  }
  if (originalCode === "class_evening_self_study_day")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        period_scope: "regular",
        periods: [8, 9],
        params: {
          choose_count:
            rule.choiceCount ||
            (rule.quantity.match(/\d+/)
              ? Number(rule.quantity.match(/\d+/)?.[0])
              : 1),
        },
      },
    ];
  if (originalCode === "teacher_daily_limit")
    return [
      {
        ...base,
        id: `${rule.id}-load`,
        code: originalCode,
        params: { max_lessons_per_day: teacherDailyLimitCap(rule) },
      },
      {
        ...base,
        id: `${rule.id}-continuity`,
        code: "teacher_gap_free",
        params: {},
      },
    ];
  if (originalCode === "class_allowed_subjects") {
    const forbidAll =
      rule.id === "R18-b" ||
      rule.operator === "禁止安排指定节次" ||
      rule.quantity === "不排课";
    const allowedNames = rule.allowedSubjects?.length
      ? rule.allowedSubjects
      : rule.id === "R18" || rule.id === "R18-s"
        ? ["音乐", "美术", "心理"]
        : [];
    const allowedSubjectIds =
      resources?.subjects
        .filter((item) => allowedNames.includes(item.name))
        .map((item) => item.id) || [];
    if (!forbidAll && !allowedSubjectIds.length) return [fallback()];
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        params: forbidAll
          ? { allowed_subject_ids: [], forbid_all: true }
          : { allowed_subject_ids: allowedSubjectIds, require_occupied_slots: false },
      },
    ];
  }
  if (
    originalCode === "teacher_forbidden_slots" &&
    rule.specificSlots?.length
  ) {
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        weekdays: [],
        periods: [],
        params: {
          forbidden_slots: rule.specificSlots.map((slot) => ({
            weekday: slot.weekday,
            periods: slot.periods,
          })),
        },
      },
    ];
  }
  if (
    originalCode === "teacher_forbidden_slots" &&
    textMeansEvening(rule)
  ) {
    const periods = periodCodes(rule.period);
    // 晚课节次必须是网格晚自习节（当前第10节）；单位数误解析时回落到 10。
    const eveningPeriods =
      periods.length && periods.every((period) => period >= 8)
        ? periods
        : [10];
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        period_scope: "evening",
        periods: eveningPeriods,
        params: {
          source_operator: rule.operator,
          ...((rule.id === "R06" || rule.id === "R07")
            ? { require_weekdays: [1, 2] }
            : rule.id === "R14"
              ? { require_weekdays: [1, 4] }
              : {}),
        },
      },
    ];
  }
  if (originalCode === "teacher_multi_class_evening_adjacent")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        params: {
          minimum_class_count: 2,
          evening_only: true,
        },
      },
    ];
  if (originalCode === "slot_teacher_role_required") {
    const weekdays = weekdayCodes(rule.weekday);
    let periods = periodCodes(rule.period);
    const looksEvening =
      textMeansEvening(rule) ||
      periods.some((period) => period >= 10) ||
      /晚自习|晚课/.test(rule.period);
    if (
      looksEvening &&
      (!periods.length || periods.every((period) => period < 8))
    ) {
      periods = [10];
    }
    if (!weekdays.length || !periods.length) return [fallback()];
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        target: { type: "global", ids: [] },
        weekdays,
        periods,
        period_scope: looksEvening ? ("evening" as const) : ("regular" as const),
        params: {
          teacher_role: rule.requiredTeacherRole || "head_teacher",
        },
      },
    ];
  }
  if (originalCode === "teacher_evening_daytime_link") {
    const requiredPeriod =
      periodCodes(rule.period)[0] ||
      Number(rule.quantity.match(/\d+/)?.[0]) ||
      7;
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        weekdays: [],
        periods: [],
        period_scope: "any",
        params: {
          // 晚自习起始节次由课位结构推导，不在规则里写死
          required_daytime_period: requiredPeriod,
        },
      },
    ];
  }
  if (originalCode === "teacher_period_minimum") {
    const periods = periodCodes(rule.period);
    const minimum =
      Number(String(rule.quantitySpec?.amount || 0)) ||
      Number(rule.quantity.match(/\d+/)?.[0]) ||
      2;
    if (!periods.length || !ids.length || minimum < 1) return [fallback()];
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        target: { type: "teacher", ids },
        periods,
        period_scope: "regular",
        params: { minimum_lessons: minimum },
      },
    ];
  }
  if (originalCode === "slot_teacher_balance")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        target: { type: "global", ids: [] },
        params: { max_per_teacher: slotTeacherBalanceCap(rule) },
      },
    ];
  if (originalCode === "teacher_preferred_weekdays") {
    const params: Record<string, unknown> = {};
    if (rule.id === "R19-01" || rule.id === "R19-02") {
      const hit = resources?.classes.find((item) => {
        const name = normalizeTargetName(item.name);
        return rule.id === "R19-01"
          ? name.includes("10")
          : /\(7\)班/.test(name);
      });
      if (hit) params.class_id = hit.id;
    }
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        period_scope: "evening",
        periods:
          base.periods.length && base.periods.every((period) => period >= 8)
            ? base.periods
            : [10],
        params,
      },
    ];
  }
  if (originalCode === "subject_evening_parity_pair")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        period_scope: "evening",
        params: {},
      },
    ];
  if (originalCode === "subject_daytime_parity_pair") {
    const weekdays = weekdayCodes(rule.weekday);
    const periods = periodCodes(rule.period);
    const oddNames =
      rule.parityOddSubjects?.filter(Boolean) ||
      (rule.parityOddSubject ? [rule.parityOddSubject] : []);
    const evenNames =
      rule.parityEvenSubjects?.filter(Boolean) ||
      (rule.parityEvenSubject ? [rule.parityEvenSubject] : []);
    const oddIds = oddNames
      .map((name) => resources?.subjects.find((item) => item.name === name)?.id)
      .filter((id): id is number => typeof id === "number");
    const evenIds = evenNames
      .map((name) => resources?.subjects.find((item) => item.name === name)?.id)
      .filter((id): id is number => typeof id === "number");
    const overlap = oddIds.some((id) => evenIds.includes(id));
    if (
      !oddIds.length ||
      !evenIds.length ||
      oddIds.length !== oddNames.length ||
      evenIds.length !== evenNames.length ||
      overlap ||
      !weekdays.length ||
      !periods.length
    ) {
      return [fallback()];
    }
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        target: { type: "subject", ids: [...oddIds, ...evenIds] },
        weekdays,
        periods,
        period_scope: "regular",
        params: { odd_subject_ids: oddIds, even_subject_ids: evenIds },
      },
    ];
  }
  if (originalCode === "subject_prefer_early_periods")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        params: {
          max_outside: Math.max(
            0,
            Number(rule.maxOutsidePreferred ?? rule.quantitySpec?.amount) || 0,
          ),
        },
      },
    ];
  if (originalCode === "subject_gap_fill_late_periods")
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        params: { late_from_period: 8 },
      },
    ];
  if (originalCode === "class_gap_free")
    return [{ ...base, id: rule.id, code: originalCode, periods: [], params: {} }];
  if (originalCode === "teacher_forbidden_slots") {
    return [
      {
        ...base,
        id: rule.id,
        code: originalCode,
        params: {
          source_operator: rule.operator,
          ...(rule.id === "R17-01" ? { own_head_class_only: true } : {}),
        },
      },
    ];
  }
  return [{ ...base, id: rule.id, code: originalCode, params: {} }];
};

export const toApiRuleGroup = (
  group: RuleGroup,
  academicYear: string,
  term: string,
  resources?: SchedulingResources,
): SchedulingRuleGroup => ({
  id: group.id,
  name: group.name,
  academic_year: academicYear,
  term,
  version: 1,
  grade_id: group.grade_id,
  rules: group.rules.flatMap((rule) => canonicalRule(rule, resources)),
});

/** 已废弃的独立「教师无空节」（如 R03）；R04-continuity 仍保留 */
export const isOrphanTeacherGapFreeRule = (rule: {
  id: string;
  code?: string;
}) =>
  rule.code === "teacher_gap_free" &&
  rule.id !== "R04-continuity" &&
  !String(rule.id).endsWith("-continuity");

/** 把库里残留的独立 teacher_gap_free 写回清除（界面已不展示；保留其余规则原样） */
export async function purgeOrphanTeacherGapFreeGroups(
  apiGroups: SchedulingRuleGroup[],
) {
  const touched: SchedulingRuleGroup[] = [];
  for (const saved of apiGroups) {
    if (!saved.rules?.some(isOrphanTeacherGapFreeRule)) continue;
    const cleaned: SchedulingRuleGroup = {
      ...saved,
      rules: (saved.rules || []).filter(
        (rule) => !isOrphanTeacherGapFreeRule(rule),
      ),
    };
    await schedulingApi.saveRuleGroup(cleaned);
    touched.push(cleaned);
  }
  return touched;
}

const weekdayLabelFromCodes = (days: number[] | undefined) => {
  if (!days?.length) return null;
  if (days.length === 5 && days.every((day, index) => day === index + 1))
    return "周一至周五";
  if (days.length === 7) return "全周";
  if (days.length === 6 && days.every((day, index) => day === index + 1))
    return "周一至周六";
  const labels = days
    .map((day) => WEEKDAY_OPTIONS[day - 1])
    .filter(Boolean);
  return labels.length ? labels.join("、") : null;
};

const periodLabelFromCodes = (periods: number[] | undefined) => {
  if (!periods?.length) return null;
  return periods.map((period) => `第${period}节`).join("、");
};

const namesFromApiTarget = (
  target: SchedulingRuleDefinition["target"] | undefined,
  resources?: SchedulingResources,
): string | null => {
  if (!target?.ids?.length || !resources) return null;
  if (target.type === "subject") {
    const map = new Map(resources.subjects.map((item) => [item.id, item.name]));
    const names = target.ids
      .map((id) => map.get(id))
      .filter((name): name is string => Boolean(name));
    return names.length ? names.join(" / ") : null;
  }
  if (target.type === "teacher") {
    const map = new Map(resources.teachers.map((item) => [item.id, item.name]));
    const names = target.ids
      .map((id) => map.get(id))
      .filter((name): name is string => Boolean(name));
    return names.length ? names.join(" / ") : null;
  }
  if (target.type === "class") {
    const map = new Map(
      resources.classes.map((item) => [item.id, normalizeTargetName(item.name)]),
    );
    const names = target.ids
      .map((id) => map.get(id))
      .filter((name): name is string => Boolean(name));
    return names.length ? names.join(" / ") : null;
  }
  return null;
};

const shortenTargetLabel = (target: string, maxItems = 4) => {
  const parts = target
    .split(/\s*[\/、]\s*/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (parts.length <= maxItems) return parts.join("、") || "未指定";
  return `${parts.slice(0, maxItems).join("、")} 等 ${parts.length} 项`;
};

/** 列表卡片第二行：用人话说明规则，避免露出 R04-load / 教师数字 ID。 */
const ruleCardLines = (rule: GenericScheduleRule): [string, string] => {
  if (rule.id === "R04") {
    const cap = teacherDailyLimitCap(rule);
    if (rule.scope === "教师") {
      return [
        `模式：按教师 · ${shortenTargetLabel(rule.target)}`,
        `要求：工作日每天最多 ${cap} 节；白天 1～7 节中间不能空节`,
      ];
    }
    return [
      `模式：按学科 · ${shortenTargetLabel(rule.target)}`,
      `要求：这些学科的任课老师，每天最多 ${cap} 节，且 1～7 节不能空节`,
    ];
  }
  const family = RULE_FAMILY_LABELS[rule.family || familyForRule(rule)];
  return [
    `${family} · ${rule.scope} · ${shortenTargetLabel(rule.target || "")}`,
    `${rule.operator} · ${rule.weekday} · ${rule.period}`,
  ];
};

/** 用后端规则组刷新工作台；R04-load/continuity 合并成一条可读的 R04。 */
const hydrateGroupFromApi = (
  saved: SchedulingRuleGroup,
  resources?: SchedulingResources,
): RuleGroup => {
  const defaults = normalizeAmbiguousRules(DEFAULT_RULES);
  const defaultById = new Map(defaults.map((rule) => [rule.id, rule]));
  const merged: GenericScheduleRule[] = [];
  const used = new Set<string>();

  for (const apiRule of saved.rules) {
    // 独立「教师无空节」设计师已废弃：工作日无空节并进 R04；班级铺满用分布/班级无空堂。
    // R04-continuity 仍由下面的合并逻辑消化，不单独展示。
    if (
      apiRule.code === "teacher_gap_free" &&
      apiRule.id !== "R04-continuity" &&
      !String(apiRule.id).endsWith("-continuity")
    ) {
      used.add(apiRule.id);
      continue;
    }
    if (apiRule.id === "R04-continuity" || apiRule.id === "R04-load") {
      if (apiRule.id === "R04-continuity") continue;
      if (apiRule.code === "manual_review") continue;
      if (used.has("R04")) continue;
      const base = defaultById.get("R04");
      if (!base) continue;
      const isSubject = apiRule.target?.type === "subject";
      const named = namesFromApiTarget(apiRule.target, resources);
      const dailyCap =
        Number(apiRule.params?.max_lessons_per_day) ||
        teacherDailyLimitCap(base);
      merged.push({
        ...base,
        enabled: apiRule.enabled ?? base.enabled,
        priority: apiRule.priority,
        scope: isSubject ? "学科" : "教师",
        target:
          named ||
          (isSubject ? R04_SUBJECT_TARGET : "多班教师"),
        title: base.title,
        note: isSubject ? r04NoteSubject(dailyCap) : r04NoteTeacher(dailyCap),
        status: "pass",
        rule_code: "teacher_daily_limit",
        operator: "每日课节上限",
        quantity: formatTeacherDailyLimitQuantity(dailyCap),
        quantitySpec: {
          amount: dailyCap,
          unit: "per_day",
          distribution: "daily-limit",
        },
        distributionSpec: {
          target: "daily-limit",
          maxLessonsPerDay: dailyCap,
        },
      });
      used.add("R04");
      used.add("R04-load");
      used.add("R04-continuity");
      continue;
    }
    // 学科上下午分布：配套的「允许课位」不单独展示（已绑在一条 UI 规则里）
    if (apiRule.code === "subject_allowed_slots") {
      const allowSubjectIds = apiRule.target?.ids || [];
      const bundledFrom = String(apiRule.params?.bundled_from || "");
      const isCompanionId =
        apiRule.id === "R08-01" ||
        /(?:^|-)allow(?:-|$)/.test(apiRule.id) ||
        Boolean(bundledFrom);
      const hasPatternForSubject = saved.rules.some(
        (item) =>
          item.code === "class_slot_pattern" &&
          item.target?.type === "subject" &&
          allowSubjectIds.some((id) => item.target?.ids?.includes(id)),
      );
      if (isCompanionId || hasPatternForSubject) {
        used.add(apiRule.id);
        continue;
      }
    }
    const base = defaultById.get(apiRule.id);
    if (base) {
      const named = namesFromApiTarget(apiRule.target, resources);
      const balanceCap =
        apiRule.code === "slot_teacher_balance"
          ? Number(apiRule.params?.max_per_teacher) ||
            slotTeacherBalanceCap(base)
          : null;
      const weekdayFromApi = weekdayLabelFromCodes(apiRule.weekdays);
      const periodFromApi = periodLabelFromCodes(apiRule.periods);
      const periodLabel =
        apiRule.code === "slot_teacher_balance"
          ? periodFromApi || base.period
          : periodFromApi || base.period;
      merged.push({
        ...base,
        enabled: apiRule.enabled ?? base.enabled,
        priority: apiRule.priority,
        rule_code: apiRule.code,
        title: apiRule.title || base.title,
        // 必须以库里的星期/节次为准，否则保存会把后端字段写空（如 R18-lang）
        ...(weekdayFromApi ? { weekday: weekdayFromApi } : {}),
        ...(periodFromApi || apiRule.code === "slot_teacher_balance"
          ? { period: periodLabel }
          : {}),
        ...(balanceCap != null
          ? {
              period: periodLabel,
              quantity: formatSlotTeacherBalanceQuantity(balanceCap),
              quantitySpec: {
                amount: balanceCap,
                unit: "section" as QuantityUnit,
                distribution: "none",
              },
              title:
                apiRule.title ||
                slotTeacherBalanceTitle(periodLabel, balanceCap),
              note: slotTeacherBalanceNote(periodLabel, balanceCap),
            }
          : {}),
        ...(named
          ? {
              target: named,
              scope:
                apiRule.target?.type === "subject"
                  ? "学科"
                  : apiRule.target?.type === "teacher"
                    ? "教师"
                    : apiRule.target?.type === "class"
                      ? "班级"
                      : base.scope,
            }
          : {}),
        ...(apiRule.code === "subject_daytime_parity_pair"
          ? (() => {
              const oddIds = Array.isArray(apiRule.params?.odd_subject_ids)
                ? (apiRule.params.odd_subject_ids as number[])
                : [];
              const evenIds = Array.isArray(apiRule.params?.even_subject_ids)
                ? (apiRule.params.even_subject_ids as number[])
                : [];
              const nameOf = (id: number) =>
                resources?.subjects.find((item) => item.id === id)?.name || "";
              const oddNames = oddIds.map(nameOf).filter(Boolean);
              const evenNames = evenIds.map(nameOf).filter(Boolean);
              const parts = (named || "")
                .split(/\s*\/\s*/)
                .map((item) => item.trim())
                .filter(Boolean);
              const odds = oddNames.length
                ? oddNames
                : parts.slice(0, Math.max(1, Math.floor(parts.length / 2)));
              const evens = evenNames.length
                ? evenNames
                : parts.slice(odds.length);
              return {
                parityOddSubjects: odds,
                parityEvenSubjects: evens,
                target: [...odds, ...evens].join(" / "),
                kind: "配对" as RuleKind,
                cycle: "单周 / 双周",
              };
            })()
          : {}),
      });
      used.add(apiRule.id);
      continue;
    }
    const scope: RuleScope =
      apiRule.target?.type === "teacher"
        ? "教师"
        : apiRule.target?.type === "class"
          ? "班级"
          : apiRule.target?.type === "subject"
            ? "学科"
            : apiRule.target?.type === "slot"
              ? "课位"
              : "全局";
    const named = namesFromApiTarget(apiRule.target, resources);
    const weekdayLabel =
      weekdayLabelFromCodes(apiRule.weekdays) || "全周";
    const periodLabel =
      periodLabelFromCodes(apiRule.periods) ||
      (apiRule.period_scope === "evening" ? "晚课" : UNRESOLVED_PERIOD);
    const operatorForCode =
      apiRule.code === "slot_forbidden"
        ? "禁止占用指定课位"
        : apiRule.code === "subject_allowed_slots"
          ? "仅允许指定课位"
          : apiRule.code === "slot_teacher_role_required"
            ? "必须安排"
            : apiRule.code === "teacher_period_minimum"
              ? "节次课时下限"
              : apiRule.code === "subject_consecutive"
                ? "要求连堂"
                : apiRule.code === "teacher_consecutive"
                  ? "要求连堂"
                : apiRule.code === "class_slot_pattern"
                  ? "均衡分布"
                  : apiRule.code === "subject_daytime_parity_pair"
                    ? "白天单双周对课"
                    : apiRule.code === "subject_evening_parity_pair"
                      ? "单双周配对"
                  : apiRule.code === "teacher_forbidden_slots"
                ? "禁止排课"
                : apiRule.code === "teacher_gap_free"
                  ? "保持连续"
                  : apiRule.code === "teacher_daily_limit"
                    ? "每日课节上限"
                    : "禁止排课";
    const quantityForCode =
      apiRule.code === "teacher_period_minimum"
        ? `至少 ${Number(apiRule.params?.minimum_lessons) || 2} 节`
        : apiRule.code === "subject_prefer_early_periods"
          ? `允许 ${Number(apiRule.params?.max_outside) || 0} 节不在所选节次`
        : apiRule.code === "teacher_daily_limit"
          ? formatTeacherDailyLimitQuantity(
              Number(apiRule.params?.max_lessons_per_day) || 3,
            )
          : "不限定";
    const quantitySpecForCode =
      apiRule.code === "teacher_period_minimum"
        ? {
            amount: Number(apiRule.params?.minimum_lessons) || 2,
            unit: "section" as QuantityUnit,
            distribution: "none" as const,
          }
        : apiRule.code === "teacher_daily_limit"
          ? {
              amount: Number(apiRule.params?.max_lessons_per_day) || 3,
              unit: "per_day" as QuantityUnit,
              distribution: "daily-limit" as const,
            }
          : undefined;
    const distributionSpecForCode =
      apiRule.code === "subject_consecutive" || apiRule.code === "teacher_consecutive"
        ? {
            target: "consecutive" as DistributionTarget,
            consecutiveLength:
              Number(apiRule.params?.minimum_block_length) || 2,
            minimumDays: Number(apiRule.params?.minimum_days) || 1,
            ...(apiRule.code === "teacher_consecutive"
              ? {
                  teacherClassMode:
                    apiRule.params?.class_mode === "cross_class"
                      ? ("cross_class" as const)
                      : ("same_class" as const),
                }
              : {}),
          }
        : apiRule.code === "class_slot_pattern"
          ? parseSlotPatternFromApi(apiRule)
          : apiRule.code === "teacher_daily_limit"
            ? {
                target: "daily-limit" as DistributionTarget,
                maxLessonsPerDay:
                  Number(apiRule.params?.max_lessons_per_day) || 3,
              }
            : undefined;
    const stub = makeRule({
      id: apiRule.id,
      category: apiRule.period_scope === "evening" ? "evening" : "global",
      scope,
      family: RULE_TEMPLATE_MAP.get(apiRule.code as RuleTemplateId)?.family,
      target:
        named ||
        (apiRule.target?.type === "global"
          ? "全年级"
          : (apiRule.target?.ids || []).join(" / ")),
      kind:
        apiRule.code === "subject_daytime_parity_pair" ||
        apiRule.code === "subject_evening_parity_pair"
          ? "配对"
          : apiRule.priority === "hard"
            ? "禁排"
            : "偏好",
      operator: operatorForCode,
      relation: "无",
      weekday: weekdayLabel,
      period: periodLabel,
      cycle:
        apiRule.code === "subject_daytime_parity_pair" ||
        apiRule.code === "subject_evening_parity_pair"
          ? "单周 / 双周"
          : "每周",
      quantity: quantityForCode,
      ...(quantitySpecForCode ? { quantitySpec: quantitySpecForCode } : {}),
      ...(distributionSpecForCode
        ? { distributionSpec: distributionSpecForCode }
        : {}),
      priority: apiRule.priority,
      status: named || apiRule.target?.type === "global" ? "pass" : "unresolved",
      title: apiRule.title,
      note: "",
      rule_code: apiRule.code,
      ...(apiRule.code === "subject_daytime_parity_pair"
        ? (() => {
            const oddIds = Array.isArray(apiRule.params?.odd_subject_ids)
              ? (apiRule.params.odd_subject_ids as number[])
              : [];
            const evenIds = Array.isArray(apiRule.params?.even_subject_ids)
              ? (apiRule.params.even_subject_ids as number[])
              : [];
            const nameOf = (id: number) =>
              resources?.subjects.find((item) => item.id === id)?.name || "";
            const oddNames = oddIds.map(nameOf).filter(Boolean);
            const evenNames = evenIds.map(nameOf).filter(Boolean);
            const parts = (named || "")
              .split(/\s*\/\s*/)
              .map((item) => item.trim())
              .filter(Boolean);
            const odds = oddNames.length
              ? oddNames
              : parts.slice(0, Math.max(1, Math.floor(parts.length / 2)));
            const evens = evenNames.length
              ? evenNames
              : parts.slice(odds.length);
            return {
              parityOddSubjects: odds,
              parityEvenSubjects: evens,
              target: [...odds, ...evens].join(" / "),
            };
          })()
        : {}),
    });
    stub.enabled = apiRule.enabled;
    if (apiRule.code === "subject_prefer_early_periods") {
      const outside = Number(apiRule.params?.max_outside);
      stub.maxOutsidePreferred = Number.isFinite(outside) ? Math.max(0, outside) : 2;
    }
    merged.push(stub);
    used.add(apiRule.id);
  }

  // 只展示后端该综合规则里真实存在的细则；不要用高一 DEFAULT_RULES 填补空组，
  // 否则新建高二/高三会看起来「自带一整套高一规则」，破坏年级隔离。

  return migrateLegacyGroup({
    id: saved.id || "grade-1-rules",
    name: saved.name || "高一排课规则组",
    grade_id: saved.grade_id ?? null,
    scope: "",
    term: `${saved.academic_year} · 第${saved.term}学期`,
    rules: merged,
  });
};

export default function RuleGroupWorkbench({
  slotOptions = [],
  academicYear = "2026-2027",
  term = "1",
  gridConfig,
  resources,
  grades = [],
  openGroupRequest = null,
  catalogEpoch = 0,
}: RuleGroupWorkbenchProps) {
  const { message, modal } = App.useApp();
  const [groups, setGroups] = useState<RuleGroup[]>([]);
  const [loadingCatalog, setLoadingCatalog] = useState(true);
  const [activeGroupId, setActiveGroupId] = useState("grade-1");
  const group =
    groups.find((item) => item.id === activeGroupId) ||
    groups[0] ||
    loadGroup();
  useEffect(() => {
    if (!loadingCatalog && groups.length) setAssistantContext('rules', { rule_group_id: group.id, rule_group_name: group.name });
    return () => clearAssistantContext('rules');
  }, [loadingCatalog, groups.length, group.id, group.name]);
  const updateActiveGroup = (
    next: RuleGroup | ((current: RuleGroup) => RuleGroup),
  ) => {
    setGroups((prev) => {
      const targetId = activeGroupId || prev[0]?.id;
      return prev.map((item) => {
        if (item.id !== targetId) return item;
        return typeof next === "function" ? next(item) : next;
      });
    });
  };
  const [open, setOpenState] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [typePickerOpen, setTypePickerOpen] = useState(false);
  const [hintAdd, setHintAdd] = useState(false);
  useEffect(() => {
    const onHint = () => {
      setHintAdd(true)
      window.setTimeout(() => setHintAdd(false), 2800)
    }
    window.addEventListener('lc-assist-hint-rule-add', onHint)
    return () => window.removeEventListener('lc-assist-hint-rule-add', onHint)
  }, []);
  const [createForm, setCreateForm] = useState<{
    title: string;
    gradeId?: number;
  }>({ title: "" });
  const [selectedId, setSelectedId] = useState("R01");
  const [draft, setDraft] = useState<GenericScheduleRule>(
    () => group.rules[0] || blankRule("R01"),
  );
  const [isNew, setIsNew] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [familyFilter, setFamilyFilter] = useState<"all" | RuleFamily>("all");
  const [scopeFilter] = useState<"全部" | RuleScope>("全部");
  const [priorityFilter] = useState<"全部" | RulePriority>("全部");
  const getTargetOptions = (
    scope: RuleScope,
    currentTarget = "",
    options: string[] = slotOptions,
  ) => getTargetOptionsFromResources(scope, currentTarget, options, resources);
  const [statusFilter] = useState<"全部" | RuleStatus>("全部");
  const [keyword] = useState("");
  const resourceReadyKey = `${resources?.subjects?.length ?? 0}:${resources?.teachers?.length ?? 0}:${resources?.classes?.length ?? 0}`;

  const decorateGroup = (item: RuleGroup): RuleGroup => {
    const grade_id = inferGradeId(item, grades);
    return {
      ...item,
      grade_id,
      scope: ruleGroupScopeLabel(
        { ...item, grade_id },
        grades,
        resources?.classes || [],
      ),
    };
  };

  useEffect(() => {
    clearLegacyRuleGroupCache(academicYear, term);
    let active = true;
    setLoadingCatalog(true);
    schedulingApi
      .ruleGroups({ academic_year: academicYear, term })
      .then(async (catalog) => {
        if (!active) return;
        const apiGroups = catalog.groups || [];
        const next = apiGroups.map((saved) => {
          const hydrated = hydrateGroupFromApi(saved, resources);
          const grade_id =
            saved.grade_id != null
              ? Number(saved.grade_id)
              : inferGradeId(
                  { name: saved.name, scope: "", grade_id: null },
                  grades,
                );
          return decorateGroup({
            ...hydrated,
            id: saved.id,
            name: saved.name || hydrated.name,
            grade_id,
            scope: "",
            rules: hydrated.rules,
          });
        });
        setGroups(next);
        setActiveGroupId((current) =>
          next.some((item) => item.id === current)
            ? current
            : next[0]?.id || "grade-1",
        );
        const needsGradeBackfill = next.some((item) => {
          const saved = apiGroups.find((group) => group.id === item.id);
          return Boolean(item.grade_id) && saved?.grade_id !== item.grade_id;
        });
        if (needsGradeBackfill && apiGroups.length) {
          try {
            await schedulingApi.saveRuleGroups({
              academic_year: academicYear,
              term,
              active_id: catalog.active_id || next[0]?.id,
              groups: apiGroups.map((saved) => ({
                ...saved,
                grade_id:
                  next.find((item) => item.id === saved.id)?.grade_id ??
                  saved.grade_id ??
                  null,
              })),
            });
          } catch {
            /* grade_id 回填失败不阻断工作台 */
          }
        }
        // 清掉库里残留的独立 R03 等 teacher_gap_free（界面已废弃，反向校验也不该再验）
        if (
          active &&
          apiGroups.some((saved) =>
            saved.rules?.some(isOrphanTeacherGapFreeRule),
          )
        ) {
          try {
            await purgeOrphanTeacherGapFreeGroups(apiGroups);
          } catch {
            /* 清理失败不阻断工作台 */
          }
        }
        setSelectedId((current) =>
          current === "R04-load" || current === "R04-continuity"
            ? "R04"
            : current,
        );
      })
      .catch((error) => {
        if (!active) return;
        setGroups([]);
        message.error(
          error instanceof Error
            ? error.message
            : "加载综合规则失败，请检查后端服务",
        );
      })
      .finally(() => {
        if (active) setLoadingCatalog(false);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [academicYear, term, resourceReadyKey, resources, grades, catalogEpoch]);

  const visibleRules = useMemo(
    () =>
      group.rules.filter((rule) => {
        const query = keyword.trim().toLowerCase();
        return (
          (familyFilter === "all" ||
            (rule.family || familyForRule(rule)) === familyFilter) &&
          (scopeFilter === "全部" || rule.scope === scopeFilter) &&
          (priorityFilter === "全部" || rule.priority === priorityFilter) &&
          (statusFilter === "全部" || rule.status === statusFilter) &&
          (!query ||
            `${rule.title} ${rule.target} ${rule.note}`
              .toLowerCase()
              .includes(query))
        );
      }),
    [
      familyFilter,
      group.rules,
      keyword,
      priorityFilter,
      scopeFilter,
      statusFilter,
    ],
  );

  const enabledRules = group.rules.filter((rule) => rule.enabled);
  const hardCount = enabledRules.filter(
    (rule) => rule.priority === "hard",
  ).length;
  const softCount = enabledRules.filter(
    (rule) => rule.priority === "soft",
  ).length;
  const unresolvedCount = enabledRules.filter(
    (rule) => rule.status === "unresolved",
  ).length;
  const familyCounts = (Object.keys(RULE_FAMILY_LABELS) as RuleFamily[]).map(
    (family) => ({
      family,
      count: group.rules.filter(
        (rule) => (rule.family || familyForRule(rule)) === family,
      ).length,
    }),
  );
  const draftFamily = draft.family || familyForRule(draft);
  const draftCode = ruleCodeForRule(draft);
  const draftTemplate = ruleTemplateForRule(draft);
  const draftScope: RuleScope = draft.scope;
  const showRelation =
    draftFamily === "combination" || draft.operator === "组合限制";
  const showSlotTeacherBalanceCap = draftCode === "slot_teacher_balance";
  const showPeriodMinimumAmount = draftCode === "teacher_period_minimum";
  const showSubjectConsecutive = draftCode === "subject_consecutive";
  const showTeacherConsecutive = draftCode === "teacher_consecutive";
  const showConsecutive = showSubjectConsecutive || showTeacherConsecutive;
  const showSlotPattern = draftCode === "class_slot_pattern";
  const showPreferEarly = draftCode === "subject_prefer_early_periods";
  const showDistribution =
    !showSlotTeacherBalanceCap &&
    !showPeriodMinimumAmount &&
    !showConsecutive &&
    !showSlotPattern &&
    !showPreferEarly &&
    (draftFamily === "distribution" ||
      Boolean(
        draft.distributionSpec && draft.distributionSpec.target !== "none",
      ) ||
      ["尽量连续", "保持连续", "均衡分配"].includes(draft.operator));
  const showSpecificSlots = Boolean(draft.specificSlots?.length);
  const showAllowedSubjects = draftCode === "class_allowed_subjects";
  const showRequiredTeacherRole = draftCode === "slot_teacher_role_required";
  const showSelfStudyDayConfig = draftCode === "class_evening_self_study_day";
  const showDaytimeParityLegs = draftCode === "subject_daytime_parity_pair";
  const showWeekdayFields = !showSlotPattern && !showPreferEarly;
  const showPeriodField =
    !showSelfStudyDayConfig && !showConsecutive && !showSlotPattern;
  const configuredWeekdayOptions = useMemo(() => {
    const values = WEEKDAY_OPTIONS.filter((day) =>
      slotOptions.some((slot) => slot.startsWith(`${day} ·`)),
    );
    return values.length ? values : WEEKDAY_OPTIONS;
  }, [slotOptions]);
  const configuredPeriodOptions = useMemo(() => {
    const values = [
      ...new Set(
        slotOptions.flatMap((slot) => {
          const match = slot.match(/第(\d+)节$/);
          return match ? [`第${match[1]}节`] : [];
        }),
      ),
    ];
    return values.length ? values : PERIOD_OPTIONS;
  }, [slotOptions]);
  const allowedSubjectOptions = useMemo(() => {
    const values =
      resources?.subjects.map((item) => item.name) ||
      SCHEDULE_SUBJECTS.filter((value) => value !== "各学科");
    return [...new Set(values)].filter((value) => value !== "各学科");
  }, [resources]);

  const nextRuleId = () =>
    `R${String(Math.max(0, ...group.rules.map((item) => Number(item.id.replace(/\D/g, "")) || 0)) + 1).padStart(2, "0")}`;

  const gradeScopeOptions = useMemo(
    () =>
      grades.map((grade) => ({
        value: grade.id,
        label: gradeDisplayName(grade),
      })),
    [grades],
  );

  const openCreateGroup = () => {
    setCreateForm({
      title: "",
      gradeId: gradeScopeOptions[0]?.value,
    });
    setCreateOpen(true);
  };

  const openWorkbench = (rule?: GenericScheduleRule) => {
    if (!rule) {
      setTypePickerOpen(true);
      return;
    }
    setFamilyFilter("all");
    setSelectedId(rule.id);
    setDraft({ ...rule });
    setIsNew(false);
    setDirty(false);
    setOpen(true);
  };

  const enterWorkbench = (nextGroup: RuleGroup) => {
    setActiveGroupId(nextGroup.id);
    setFamilyFilter("all");
    if (nextGroup.rules.length) {
      setSelectedId(nextGroup.rules[0].id);
      setDraft({ ...nextGroup.rules[0] });
    } else {
      setSelectedId("");
      setDraft(blankRule("R01"));
    }
    setIsNew(false);
    setDirty(false);
    setOpen(true);
  };

  const openedFocusToken = useRef<number | null>(null);
  useEffect(() => {
    if (!openGroupRequest?.groupId) return;
    if (openedFocusToken.current === openGroupRequest.token && open) return;
    const target = groups.find((item) => item.id === openGroupRequest.groupId);
    if (!target) return;
    openedFocusToken.current = openGroupRequest.token;
    enterWorkbench(target);
  }, [openGroupRequest?.token, openGroupRequest?.groupId, groups, open]);

  const startNewRule = (templateId: RuleTemplateId) => {
    const template = RULE_TEMPLATE_MAP.get(templateId);
    if (!template) return;
    const next = {
      ...blankRule(nextRuleId()),
      family: template.family,
      category: template.category,
      scope: template.scope,
      operator: template.operator,
      kind: RULE_KIND_BY_ACTION[template.operator] || "禁排",
      rule_code: template.id,
      title: template.label,
      status: "unresolved" as RuleStatus,
      note: "",
    };
    if (template.id === "class_evening_self_study_day") {
      Object.assign(next, {
        weekday: "周三、周四、周五",
        period: "第8、9节",
        quantity: "1天",
        priority: "hard" as RulePriority,
        status: "pass" as RuleStatus,
        note: "在候选工作日中选择一天第8、9节保持自习。晚自习仍须排满。",
      });
    }
    if (template.id === "class_slot_pattern") {
      Object.assign(next, {
        scope: "学科" as RuleScope,
        target: "",
        weekday: "周二、周四",
        period: "第3、4、6、7节",
        quantity: "不限定",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        distributionSpec: {
          target: "morning-afternoon" as DistributionTarget,
          patternMode: "either-direction" as const,
          patternWeekdays: [2, 4],
          morningPeriods: [3, 4],
          afternoonPeriods: [6, 7],
        },
        note: "自选对开星期与上午/下午节次；保存时写入允许课位 + 两种交叉方案。周课时从课时管理读。",
      });
    }
    if (template.id === "subject_consecutive") {
      Object.assign(next, {
        scope: "学科" as RuleScope,
        target: "",
        weekday: "周一至周五",
        period: UNRESOLVED_PERIOD,
        quantity: "不限定",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        distributionSpec: {
          target: "consecutive" as DistributionTarget,
          consecutiveLength: 2,
          minimumDays: 1,
        },
        note: "勾选学科；可限制星期。每周至少 M 天出现连续 L 节该学科（默认 2 节×1 天）。",
      });
    }
    if (template.id === "teacher_consecutive") {
      Object.assign(next, {
        scope: "教师" as RuleScope,
        target: "",
        weekday: "周一至周五",
        period: UNRESOLVED_PERIOD,
        quantity: "不限定",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        distributionSpec: {
          target: "consecutive" as DistributionTarget,
          consecutiveLength: 2,
          minimumDays: 1,
          teacherClassMode: "same_class" as const,
        },
        note: "勾选教师；可选择同一班连堂或跨班连堂。每周至少 M 天出现连续 L 节。",
      });
    }
    if (template.id === "teacher_period_minimum") {
      Object.assign(next, {
        scope: "教师" as RuleScope,
        target: "",
        weekday: "周一至周六",
        period: "第3、4、5节",
        quantity: "至少 2 节",
        quantitySpec: {
          amount: 2,
          unit: "section" as QuantityUnit,
          distribution: "none",
        },
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        note: "勾选教师、星期和节次集合，再设合计下限。不必同一天；未选星期表示按生成天数全覆盖。",
      });
    }
    if (template.id === "subject_daytime_parity_pair") {
      Object.assign(next, {
        scope: "学科" as RuleScope,
        target: "",
        weekday: "未指定",
        period: UNRESOLVED_PERIOD,
        cycle: "单周 / 双周",
        quantity: "同格对腿",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        kind: "配对" as RuleKind,
        parityOddSubjects: [],
        parityEvenSubjects: [],
        note: "单周学科组（如化学、生物）与双周学科组（如历史、地理）在同一课位对腿；组内谁跟谁不规定。课时填 0.5、周次无规定即可。",
      });
    }
    if (template.id === "slot_forbidden") {
      Object.assign(next, {
        scope: "学科" as RuleScope,
        target: "",
        weekday: "周一至周五",
        period: UNRESOLVED_PERIOD,
        quantity: "不限定",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        note: "勾选作用对象与禁排课位。学科：这些学科不能上；教师：这些老师不能上；班级/全局：对应班或全年级该课位必须空着。",
      });
    }
    if (template.id === "subject_allowed_slots") {
      Object.assign(next, {
        scope: "学科" as RuleScope,
        target: "",
        weekday: "周一至周五",
        period: UNRESOLVED_PERIOD,
        quantity: "不限定",
        priority: "hard" as RulePriority,
        status: "unresolved" as RuleStatus,
        note: "硬约束：勾选的学科只能排在下面勾选的星期和节次，其它课位一律不能排这些学科。",
      });
    }
    if (template.id === "slot_teacher_role_required") {
      Object.assign(next, {
        scope: "全局" as RuleScope,
        target: "全年级",
        weekday: "周六",
        period: "第10节",
        quantity: "每班 1 节",
        priority: "hard" as RulePriority,
        status: "pass" as RuleStatus,
        requiredTeacherRole: "head_teacher" as const,
        note: "勾选的星期和节次，每个班必须由本班班主任上课。可改星期/节次，例如周一至周五第5节。",
      });
    }
    setFamilyFilter("all");
    setSelectedId(next.id);
    setDraft(next);
    setIsNew(true);
    setDirty(true);
    setTypePickerOpen(false);
    setOpen(true);
  };

  const confirmCreateGroup = async () => {
    if (!createForm.title.trim()) {
      message.warning("请填写规则名称");
      return;
    }
    if (!createForm.gradeId) {
      message.warning("请选择作用范围（年级）");
      return;
    }
    const nextGroup: RuleGroup = decorateGroup({
      id: `grade-${Date.now()}`,
      name: createForm.title.trim(),
      grade_id: createForm.gradeId,
      scope: "",
      term: `${academicYear} · 第${term}学期`,
      rules: [],
    });
    try {
      await schedulingApi.saveRuleGroup(
        toApiRuleGroup(nextGroup, academicYear, term, resources),
      );
      setGroups((prev) => [...prev, nextGroup]);
      setCreateOpen(false);
      enterWorkbench(nextGroup);
      message.success("综合规则已创建并写入后端");
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "创建综合规则失败",
      );
    }
  };

  const selectRule = (rule: GenericScheduleRule) => {
    if (dirty) {
      message.warning("请先保存当前规则，再切换其他明细");
      return;
    }
    setSelectedId(rule.id);
    setDraft({ ...rule });
    setIsNew(false);
  };

  useEffect(() => {
    if (!open) return;
    const familyByLabel: Record<string, "all" | RuleFamily> = {
      全部规则: "all",
      [RULE_FAMILY_LABELS.slot]: "slot",
      [RULE_FAMILY_LABELS.distribution]: "distribution",
      [RULE_FAMILY_LABELS.teacher]: "teacher",
      [RULE_FAMILY_LABELS.class]: "class",
      [RULE_FAMILY_LABELS.combination]: "combination",
    };
    const buttons = Array.from(
      document.querySelectorAll<HTMLButtonElement>(".rule-group-tree button"),
    );
    const handleCategoryClick = (event: Event) => {
      const button = event.currentTarget as HTMLButtonElement;
      const label = Object.keys(familyByLabel).find((value) =>
        button.textContent?.trim().startsWith(value),
      );
      const next = label ? familyByLabel[label] : undefined;
      if (!next) return;
      if (dirty) {
        message.warning("请先保存当前规则，再切换分类");
        return;
      }
      setFamilyFilter(next);
      buttons.forEach((item) =>
        item.classList.toggle("is-active", item === button),
      );
    };
    buttons.forEach((button) =>
      button.addEventListener("click", handleCategoryClick),
    );
    return () =>
      buttons.forEach((button) =>
        button.removeEventListener("click", handleCategoryClick),
      );
  }, [dirty, message, open]);

  useEffect(() => {
    if (
      !open ||
      isNew ||
      !visibleRules.length ||
      visibleRules.some((rule) => rule.id === selectedId)
    )
      return;
    const next = visibleRules[0];
    setSelectedId(next.id);
    setDraft({ ...next });
    setDirty(false);
  }, [isNew, open, selectedId, visibleRules]);

  const updateDraft = <K extends keyof GenericScheduleRule>(
    key: K,
    value: GenericScheduleRule[K],
  ) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setDirty(true);
  };

  const handleScopeChange = (scope: RuleScope) => {
    const targetOptions = getTargetOptions(scope, "", slotOptions);
    setDraft((current) => {
      if (current.id === "R04") {
        const cap = teacherDailyLimitCap(current);
        return {
          ...current,
          scope,
          target:
            scope === "学科"
              ? R04_SUBJECT_TARGET
              : targetOptions.includes("多班教师")
                ? "多班教师"
                : "",
          note:
            scope === "学科" ? r04NoteSubject(cap) : r04NoteTeacher(cap),
        };
      }
      if (ruleCodeForRule(current) === "slot_forbidden" && scope === "全局") {
        return {
          ...current,
          scope,
          target: "全年级",
          status: "pass" as RuleStatus,
        };
      }
      return {
        ...current,
        scope,
        target: targetOptions.includes(current.target) ? current.target : "",
      };
    });
    setDirty(true);
  };

  const handleTargetChange = (targetValue: string | string[]) => {
    const roleTargets = ["多班教师", "班主任", "科任教师"];
    const target = Array.isArray(targetValue)
      ? (() => {
          const last = targetValue[targetValue.length - 1];
          if (last && roleTargets.includes(last)) return last;
          return targetValue
            .filter((name) => !roleTargets.includes(name))
            .join(" / ");
        })()
      : targetValue;
    if (draft.scope !== "课位") {
      updateDraft("target", target);
      return;
    }
    const match = target.match(/^(周[一二三四五六日])\s*[·•]\s*第(\d+)节$/);
    setDraft((current) => ({
      ...current,
      target,
      weekday: match ? match[1] : current.weekday,
      period: match ? `第${match[2]}节` : current.period,
    }));
    setDirty(true);
  };

  const handleDistributionChange = (distributionSpec: DistributionSpec) => {
    const operator =
      draftFamily === "distribution"
        ? distributionSpec.target === "consecutive"
          ? "要求连堂"
          : distributionSpec.target === "morning-afternoon"
            ? "均衡分布"
            : draft.operator
        : draft.operator;
    const isDailyLimit = distributionSpec.target === "daily-limit";
    const dailyCap = isDailyLimit
      ? Math.max(1, Math.min(9, Number(distributionSpec.maxLessonsPerDay) || 3))
      : undefined;
    setDraft((current) => ({
      ...current,
      operator,
      kind: RULE_KIND_BY_ACTION[operator] || current.kind,
      distributionSpec: isDailyLimit
        ? { ...distributionSpec, maxLessonsPerDay: dailyCap }
        : distributionSpec,
      distributionTarget: distributionSpec.target,
      quantity: isDailyLimit
        ? formatTeacherDailyLimitQuantity(dailyCap || 3)
        : "不限定",
      quantitySpec: isDailyLimit
        ? {
            amount: dailyCap,
            unit: "per_day",
            distribution: "daily-limit",
          }
        : {
            amount: undefined,
            unit: "unlimited",
            distribution: distributionSpec.target,
          },
      ...(current.id === "R04" && isDailyLimit
        ? {
            note:
              current.scope === "学科"
                ? r04NoteSubject(dailyCap)
                : r04NoteTeacher(dailyCap),
          }
        : {}),
    }));
    setDirty(true);
  };

  const handleSlotTeacherBalanceCapChange = (value: number | null) => {
    const amount = Math.max(1, Math.min(20, Number(value) || 2));
    setDraft((current) => ({
      ...current,
      quantity: formatSlotTeacherBalanceQuantity(amount),
      quantitySpec: {
        amount,
        unit: "section",
        distribution: "none",
      },
      title: slotTeacherBalanceTitle(current.period, amount),
      note: slotTeacherBalanceNote(current.period, amount),
    }));
    setDirty(true);
  };

  const saveDraft = async () => {
    const savingCode = ruleCodeForRule(draft);
    const isGlobalScopedRule =
      (savingCode === "slot_forbidden" && draft.scope === "全局") ||
      savingCode === "slot_teacher_role_required";
    if (!draft.title.trim()) {
      message.warning("请填写规则名称");
      return;
    }
    if (!isGlobalScopedRule && !draft.target.trim()) {
      message.warning("请填写规则名称和作用对象");
      return;
    }
    if (savingCode === "slot_forbidden") {
      if (!weekdaySelections(draft.weekday).length) {
        message.warning("请选择禁排的星期");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择禁排的节次");
        return;
      }
    }
    if (savingCode === "subject_prefer_early_periods") {
      if (!draft.target.trim()) {
        message.warning("请至少选择一个学科");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择主科尽量安排的节次");
        return;
      }
    }
    if (savingCode === "subject_allowed_slots") {
      if (!draft.target.trim()) {
        message.warning("请至少选择一个学科");
        return;
      }
      if (!weekdaySelections(draft.weekday).length) {
        message.warning("请选择允许排课的星期");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择允许排课的节次");
        return;
      }
    }
    if (savingCode === "slot_teacher_role_required") {
      if (!weekdaySelections(draft.weekday).length) {
        message.warning("请选择必须由班主任上课的星期");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择必须由班主任上课的节次");
        return;
      }
      if ((draft.requiredTeacherRole || "head_teacher") !== "head_teacher") {
        message.warning("目前只支持班主任角色");
        return;
      }
    }
    if (savingCode === "teacher_period_minimum") {
      if (!draft.target.trim()) {
        message.warning("请至少选择一位教师");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择计入下限的节次集合");
        return;
      }
      const minimum =
        Number(draft.quantitySpec?.amount) ||
        Number(String(draft.quantity || "").match(/\d+/)?.[0]) ||
        0;
      if (minimum < 1) {
        message.warning("请设置至少 1 节的课时下限");
        return;
      }
    }
    if (savingCode === "subject_consecutive" || savingCode === "teacher_consecutive") {
      if (!draft.target.trim()) {
        message.warning(savingCode === "teacher_consecutive" ? "请至少选择一位教师" : "请至少选择一个学科");
        return;
      }
      if (!weekdaySelections(draft.weekday).length) {
        message.warning("请选择连堂统计的星期");
        return;
      }
      const blockLength = draft.distributionSpec?.consecutiveLength || 0;
      const minimumDays = draft.distributionSpec?.minimumDays || 0;
      if (blockLength < 2) {
        message.warning("连堂连续长度至少 2 节");
        return;
      }
      if (minimumDays < 1) {
        message.warning("每周至少天数不能小于 1");
        return;
      }
    }
    if (savingCode === "class_slot_pattern") {
      if (!draft.target.trim()) {
        message.warning("请至少选择一个学科");
        return;
      }
      const pattern = resolveSlotPattern(
        draft.distributionSpec,
        draft.weekday,
        draft.period,
      );
      if (pattern.weekdays.length !== 2) {
        message.warning("上下午对开请恰好选择 2 个星期");
        return;
      }
      if (!pattern.morning.length || !pattern.afternoon.length) {
        message.warning("请分别选择上午节次和下午节次");
        return;
      }
    }
    if (savingCode === "subject_daytime_parity_pair") {
      const odds = (draft.parityOddSubjects || []).filter(Boolean);
      const evens = (draft.parityEvenSubjects || []).filter(Boolean);
      if (!odds.length || !evens.length) {
        message.warning("请分别选择单周学科组和双周学科组");
        return;
      }
      if (odds.some((name) => evens.includes(name))) {
        message.warning("单周与双周学科组不能有重叠");
        return;
      }
      if (!weekdaySelections(draft.weekday).length) {
        message.warning("请选择对课作用的星期");
        return;
      }
      if (!periodCodes(draft.period).length) {
        message.warning("请选择对课作用的节次");
        return;
      }
      draft.target = [...odds, ...evens].join(" / ");
    }
    if (
      savingCode === "class_allowed_subjects" &&
      !draft.allowedSubjects?.length &&
      draft.operator !== "禁止安排指定节次" &&
      draft.quantity !== "不排课" &&
      draft.id !== "R18-b"
    ) {
      message.warning("请至少选择一个允许科目");
      return;
    }
    if (ruleCodeForRule(draft) === "class_evening_self_study_day") {
      const candidateDays = weekdaySelections(draft.weekday);
      if (candidateDays.length < 2) {
        message.warning("自习日规则至少需要选择两个候选星期");
        return;
      }
      if (!draft.choiceCount || draft.choiceCount > candidateDays.length) {
        message.warning("自习日选择数量不能超过候选星期数量");
        return;
      }
    }
    const nextRule = {
      ...draft,
      target: isGlobalScopedRule
        ? draft.target.trim() || "全年级"
        : draft.target.trim(),
      title: draft.title.trim(),
      status:
        (savingCode === "slot_forbidden" &&
          (isGlobalScopedRule || draft.target.trim())) ||
        (savingCode === "subject_allowed_slots" && draft.target.trim()) ||
        savingCode === "slot_teacher_role_required" ||
        (savingCode === "teacher_period_minimum" && draft.target.trim()) ||
        (savingCode === "subject_consecutive" && draft.target.trim()) ||
        (savingCode === "teacher_consecutive" && draft.target.trim()) ||
        (savingCode === "class_slot_pattern" && draft.target.trim()) ||
        (savingCode === "subject_daytime_parity_pair" &&
          Boolean(
            draft.parityOddSubjects?.length && draft.parityEvenSubjects?.length,
          ))
          ? ("pass" as RuleStatus)
          : draft.status,
    };
    const nextGroup = {
      ...group,
      rules: isNew
        ? [...group.rules, nextRule]
        : group.rules.map((rule) => (rule.id === draft.id ? nextRule : rule)),
    };
    updateActiveGroup(nextGroup);
    setDirty(false);
    setIsNew(false);
    try {
      await schedulingApi.saveRuleGroup(
        toApiRuleGroup(nextGroup, academicYear, term, resources),
      );
      message.success("规则明细已保存，并已写入后端规则组");
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : "写入后端失败，请检查网络后重试",
      );
    }
  };

  const closeWorkbench = () => {
    if (dirty) {
      modal.confirm({
        title: "有未保存的修改",
        content: "启用/停用或字段改动还没点「保存规则」，关闭后会丢失。确定关闭？",
        okText: "仍要关闭",
        cancelText: "回去保存",
        centered: true,
        zIndex: 5000,
        getContainer: () => document.body,
        onOk: () => {
          setDirty(false);
          setOpenState(false);
        },
      });
      return;
    }
    setDirty(false);
    setOpenState(false);
  };

  const setOpen = (next: boolean) => {
    if (next) setOpenState(true);
    else closeWorkbench();
  };

  const deleteRule = () => {
    if (isNew) {
      setIsNew(false);
      setDirty(false);
      const fallback = group.rules[0];
      if (fallback) {
        setSelectedId(fallback.id);
        setDraft({ ...fallback });
      }
      return;
    }
    // 必须用 App.modal：静态 Modal.confirm 会落在工作台大弹层后面，看起来像点了没反应
    modal.confirm({
      title: "删除规则明细",
      content: `确定删除“${draft.title}”吗？删除后会立刻写入后端。`,
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      centered: true,
      zIndex: 5000,
      getContainer: () => document.body,
      onOk: async () => {
        const deletingId = draft.id;
        const nextRules = group.rules.filter((rule) => rule.id !== deletingId);
        const nextGroup = { ...group, rules: nextRules };
        try {
          await schedulingApi.saveRuleGroup(
            toApiRuleGroup(nextGroup, academicYear, term, resources),
          );
          updateActiveGroup(nextGroup);
          setDirty(false);
          setIsNew(false);
          const nextSelected =
            nextRules.find((rule) => rule.id === selectedId && rule.id !== deletingId) ||
            nextRules[0];
          if (nextSelected) {
            setSelectedId(nextSelected.id);
            setDraft({ ...nextSelected });
          } else {
            setSelectedId("");
            setDraft(blankRule("R01"));
          }
          message.success("规则明细已删除，并已写入后端");
        } catch (error) {
          message.error(
            error instanceof Error
              ? error.message
              : "删除失败，请检查网络后重试",
          );
          throw error;
        }
      },
    });
  };

  return (
    <div className="rule-group-page">
      <div className="rule-group-heading">
        <div>
          <span className="rule-group-eyebrow">
            RULE GROUP · GENERAL CONSTRAINTS
          </span>
          <h2>综合排课规则</h2>
          <p>按年级维护综合规则；每条综合规则进工作台配置内部细则。</p>
        </div>
        <Space>
          <Tag color="blue">{groups.length} 条规则</Tag>
          <Button type="primary" onClick={openCreateGroup}>
            ＋ 新增规则
          </Button>
        </Space>
      </div>

      <div className="rule-group-directory">
        {loadingCatalog ? (
          <div className="rule-group-row">
            <div className="rule-group-name">
              <div>
                <strong>正在从后端加载综合规则…</strong>
                <small>数据以数据库为准，不再使用本地缓存</small>
              </div>
            </div>
          </div>
        ) : null}
        {!loadingCatalog && !groups.length ? (
          <div className="rule-group-row">
            <div className="rule-group-name">
              <div>
                <strong>暂无综合规则</strong>
                <small>点击右上角「新增规则」，选择适用年级后写入后端</small>
              </div>
            </div>
          </div>
        ) : null}
        {groups.map((item) => {
          const stats = summarizeGroup(item);
          return (
            <div className="rule-group-row" key={item.id}>
              <div className="rule-group-name">
                <span>✦</span>
                <div>
                  <strong>{item.name}</strong>
                  <small>
                    {item.term} · {item.rules.length} 条细则
                  </small>
                </div>
              </div>
              <div>
                <Tag color="cyan">作用范围</Tag>
                <small>
                  {ruleGroupScopeLabel(
                    item,
                    grades,
                    resources?.classes || [],
                  )}
                </small>
              </div>
              <div>
                <Tag color="geekblue">综合规则</Tag>
                <small>{stats.typeSummary || "工作台内维护细则"}</small>
              </div>
              <div>
                <small>
                  {stats.familyCounts
                    .filter((entry) => entry.count > 0)
                    .map(
                      (entry) =>
                        `${RULE_FAMILY_LABELS[entry.family]} ${entry.count}`,
                    )
                    .join(" · ") || "暂无细则"}
                </small>
              </div>
              <div>
                <Tag color="gold">{stats.hard} 硬约束</Tag>
                <small>{stats.soft} 软目标</small>
              </div>
              <div>
                <Tag color={stats.enabled.length ? "green" : "default"}>
                  {stats.enabled.length ? "启用" : "停用"}
                </Tag>
                <small>
                  {stats.enabled.length}/{item.rules.length} 生效
                </small>
              </div>
              <Button
                type="primary"
                onClick={() => enterWorkbench(item)}
              >
                编辑进入工作台
              </Button>
            </div>
          );
        })}
      </div>

      <Modal
        title="新增综合规则"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={confirmCreateGroup}
        okText="进入工作台"
        cancelText="取消"
        width={520}
        destroyOnClose
      >
        <div className="rule-group-create-form">
          <p>
            这里创建的是一整条综合排课规则（不是内部细则）。确认后进入工作台，再配置课位、教师、班级等具体要求。
          </p>
          <label>
            <span className="rule-group-field-label">规则名称</span>
            <Input
              value={createForm.title}
              placeholder="例如：高一组排课规则"
              onChange={(event) =>
                setCreateForm((prev) => ({
                  ...prev,
                  title: event.target.value,
                }))
              }
            />
          </label>
          <label>
            <span className="rule-group-field-label">作用范围</span>
            <Select
              style={{ width: "100%" }}
              value={createForm.gradeId}
              placeholder="请选择适用年级"
              options={gradeScopeOptions}
              onChange={(gradeId: number) =>
                setCreateForm((prev) => ({ ...prev, gradeId }))
              }
            />
            <small>选择这条综合规则作用在高一年级、高二年级还是高三年级。</small>
          </label>
        </div>
      </Modal>

      <Modal
        className="rule-type-picker-modal"
        title="选择内部规则类型"
        open={typePickerOpen}
        onCancel={() => setTypePickerOpen(false)}
        footer={null}
        width={1080}
        destroyOnClose
        zIndex={5000}
        getContainer={() => document.body}
      >
        <div className="rule-group-template-picker">
          <p>在工作台内新增一条细则时，先选规则类型，再配置字段。</p>
          {(Object.keys(RULE_FAMILY_LABELS) as RuleFamily[]).map((family) => {
            const templates = RULE_TEMPLATES.filter(
              (template) => template.family === family,
            );
            if (!templates.length) return null;
            return (
              <section key={family}>
                <h4>{RULE_FAMILY_LABELS[family]}</h4>
                <div className="rule-group-template-grid">
                  {templates.map((template) => (
                    <button
                      key={template.id}
                      type="button"
                      className="rule-group-template-card"
                      onClick={() => startNewRule(template.id)}
                    >
                      <strong>{template.label}</strong>
                      <span>{template.description}</span>
                    </button>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </Modal>

      <Modal
        className="rule-group-workbench-modal"
        title={
          <div>
            <span className="rule-group-eyebrow">{group.term}</span>
            <strong>{group.name} · 规则工作台</strong>
          </div>
        }
        open={open}
        onCancel={closeWorkbench}
        footer={null}
        width="calc(100vw - 24px)"
        centered={false}
        zIndex={1200}
        maskClosable
        destroyOnClose={false}
        styles={{
          content: { height: "calc(100vh - 24px)", maxHeight: "calc(100vh - 24px)" },
          body: { height: "100%", overflow: "hidden" },
        }}
      >
        <div className="rule-group-workbench">
          <aside className="rule-group-sidebar">
            <div className="rule-group-sidebar-head">
              <span>RULE GROUP</span>
              <strong>{group.rules.length} 条明细</strong>
            </div>
            <div className="rule-group-tree">
              <button className="is-active" type="button">
                全部规则 <span>{group.rules.length}</span>
              </button>
              {familyCounts.map((item) => (
                <button key={item.family} type="button">
                  {RULE_FAMILY_LABELS[item.family]} <span>{item.count}</span>
                </button>
              ))}
            </div>
            <div className="rule-group-sidebar-note">
              <strong>怎么读</strong>
              <span>
                左边点一条规则，中间看「谁 + 干什么」。保存只写入数据库，不读浏览器缓存。
              </span>
            </div>
          </aside>
          <section className="rule-group-list">
            <div className="rule-group-panel-head">
              <div>
                <h3>规则明细</h3>
              </div>
              <Space size={8}>
                <Tag color="blue">
                  {visibleRules.length} / {group.rules.length}
                </Tag>
                <Button
                  className={`rule-group-add-btn${hintAdd ? ' is-assist-pulse' : ''}`}
                  size="small"
                  type="primary"
                  title="新增规则"
                  aria-label="新增规则"
                  onClick={() => openWorkbench()}
                >
                  +
                </Button>
              </Space>
            </div>
            <div className="rule-group-list-scroll">
              {visibleRules.map((rule) => (
                <button
                  key={rule.id}
                  className={`rule-group-card ${rule.id === selectedId ? "is-selected" : ""} ${!rule.enabled ? "is-disabled" : ""}`}
                  type="button"
                  onClick={() => selectRule(rule)}
                >
                  <div>
                    <span>{rule.id}</span>
                    <Tag color={rule.priority === "hard" ? "blue" : "gold"}>
                      {rule.priority === "hard" ? "硬约束" : "软目标"}
                    </Tag>
                  </div>
                  <strong>{rule.title}</strong>
                  {(() => {
                    const [line1, line2] = ruleCardLines(rule);
                    return (
                      <>
                        <small>{line1}</small>
                        <small>{line2}</small>
                      </>
                    );
                  })()}
                </button>
              ))}
              {!visibleRules.length && (
                <div className="rule-group-empty">没有匹配的规则明细</div>
              )}
            </div>
          </section>
          <section className="rule-group-editor">
            <div className="rule-group-panel-head">
              <div>
                <h3>{isNew ? "新增规则" : "编辑规则"}</h3>
                <p>改完点保存，会立刻写入后端数据库。</p>
              </div>
              <Tag>{draft.id === "R04" ? "R04" : draft.id}</Tag>
            </div>
            <div className="rule-group-form">
              {draft.id === "R04" && (
                <div className="rule-group-form-wide rule-group-plain-explain">
                  <strong>这条规则在说什么</strong>
                  <p>
                    核心是工作日
                    <b>
                      {formatTeacherDailyLimitQuantity(
                        teacherDailyLimitCap(draft),
                      )}
                    </b>
                    ；同时附带白天 <b>第 1～7 节中间不能空节</b>
                    。节数在下方「排课目标」里改。
                  </p>
                  <p>
                    <b>学科模式</b>
                    ：勾选学科 → 覆盖这些学科的全部任课老师（建议不要勾体育）。
                    <br />
                    <b>教师模式</b>
                    ：直接勾老师，或选「多班教师」→ 只约束名单里的人。
                  </p>
                  <p>
                    在「选模式」里切换即可。页面只显示一条；保存时会拆成「每日上限 + 不空节」两条算法规则。
                  </p>
                </div>
              )}
              <div className="rule-group-form-wide rule-group-template-info">
                <span className="rule-group-field-label">规则类型</span>
                <Tag color="blue">
                  {draft.id === "R04"
                    ? draft.scope === "教师"
                      ? "教师模式 · 课节上限"
                      : "学科模式 · 课节上限"
                    : draftTemplate?.label || "自定义规则"}
                </Tag>
                <small>
                  {showSlotPattern
                    ? "选学科即可。课位与上下午组合由模板固定，页面只展示示意。"
                    : draft.id === "R04"
                      ? draft.scope === "教师"
                        ? "按教师点名限制每天最多节数（并附带白天不空节）。可改回「学科」批量覆盖。"
                        : "按学科覆盖任课老师：每天最多 N 节，并附带白天不空节。可改成「教师」点名。"
                      : draftTemplate?.description ||
                        "未绑定算法的规则不会参与自动排课。"}
                </small>
              </div>
              <label>
                <span className="rule-group-field-label">
                  规则名称
                  <Tooltip title="给这条规则起一个便于识别的名称，例如：学科连堂">
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <Input
                  value={draft.title}
                  onChange={(event) => updateDraft("title", event.target.value)}
                />
              </label>
              {!showSlotPattern && (
              <label>
                <span className="rule-group-field-label">
                  规则类别
                  <Tooltip title="由规则模板决定，不可手改">
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <ReadonlyValue
                  value={RULE_FAMILY_LABELS[draftFamily]}
                  empty="未设置类别"
                />
              </label>
              )}
              {!showSlotPattern && (
              <label>
                <span className="rule-group-field-label">
                  {draft.id === "R04" ? "选模式" : "作用对象"}
                  <Tooltip
                    title={
                      draft.id === "R04"
                        ? "学科=按学科覆盖任课老师；教师=直接点名老师。两种模式约束内容相同。"
                        : "规则类别会限制可选的作用对象，避免规则与对象类型不匹配"
                    }
                  >
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <Select
                  value={draft.scope}
                  onChange={handleScopeChange}
                  options={scopeOptionsForRule(draftFamily, draftCode).map(
                    (value) => ({
                      value,
                      label:
                        draft.id === "R04" && value === "学科"
                          ? "学科模式"
                          : draft.id === "R04" && value === "教师"
                            ? "教师模式"
                            : value,
                    }),
                  )}
                />
              </label>
              )}
              {!(
                (draftCode === "slot_forbidden" && draft.scope === "全局") ||
                draftCode === "slot_teacher_role_required" ||
                showDaytimeParityLegs
              ) && (
              <label>
                <span className="rule-group-field-label">
                  {draft.id === "R04"
                    ? draftScope === "教师"
                      ? "选择教师"
                      : "选择学科"
                    : draftScope === "教师" ||
                        draftCode === "teacher_period_minimum"
                      ? "选择教师"
                      : draftCode === "subject_allowed_slots" ||
                          draftCode === "subject_consecutive" ||
                          draftCode === "teacher_consecutive" ||
                          draftCode === "class_slot_pattern" ||
                          (draftCode === "slot_forbidden" &&
                            draftScope === "学科")
                        ? "选择学科"
                        : draftCode === "slot_forbidden" &&
                            draftScope === "班级"
                          ? "选择班级"
                          : "对象名称"}
                  <Tooltip
                    title={
                      draft.id === "R04" && draft.scope === "学科"
                        ? "学科模式：上限/无空节作用于这些学科的全部任课教师；不勾体育即可放宽体育老师"
                        : draft.id === "R04" && draft.scope === "教师"
                          ? "教师模式：只约束你勾选的老师；可选「多班教师」一键覆盖教多个班的老师"
                          : draftCode === "teacher_period_minimum"
                            ? "可多选教师；也可选「多班教师」覆盖教多个班的老师。"
                            : draftCode === "subject_consecutive"
                              ? "可多选学科；每个学科各自要求每周至少 M 天连堂。"
                              : draftCode === "teacher_consecutive"
                                ? "可多选教师；每位教师各自要求每周至少 M 天连堂。"
                              : draftCode === "class_slot_pattern"
                                ? "可多选；保存时每个学科拆成一条课位组合规则。"
                                : draftCode === "subject_allowed_slots"
                                ? "可多选学科。这些学科只能落在下方勾选的星期和节次。"
                                : draftCode === "slot_forbidden"
                                  ? "可多选。学科禁排只挡这些学科；教师禁排只挡这些老师；班级禁排让该班对应课位空着。"
                                  : "从已配置的学科、教师、班级或具体课位中选择"
                    }
                  >
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <Select
                  showSearch
                  optionFilterProp="label"
                  maxTagCount={isMultiNameTargetRule(draft) ? 8 : undefined}
                  maxCount={
                    draftCode === "subject_evening_parity_pair" ? 2 : undefined
                  }
                  mode={
                    isMultiNameTargetRule(draft) ? "multiple" : undefined
                  }
                  value={
                    isMultiNameTargetRule(draft)
                      ? draft.target
                        ? draft.target.split(/\s*[\/、]\s*/).filter(Boolean)
                        : []
                      : draft.target || undefined
                  }
                  onChange={handleTargetChange}
                  options={getTargetOptions(
                    draft.scope,
                    draft.target,
                    slotOptions,
                  ).map((value) => ({ value, label: value }))}
                  placeholder={
                    draftScope === "课位"
                      ? "请选择具体课位"
                      : draftScope === "教师" ||
                          draftCode === "teacher_period_minimum"
                        ? "搜索并多选教师，也可选「多班教师」"
                        : draftCode === "slot_forbidden" &&
                            draftScope === "班级"
                          ? "请选择班级（可多选）"
                          : draftCode === "subject_consecutive" ||
                              draftCode === "teacher_consecutive" ||
                              draftCode === "class_slot_pattern" ||
                              draftCode === "subject_allowed_slots" ||
                              isMultiNameTargetRule(draft)
                            ? "请选择科目（可多选）"
                            : "请选择对象"
                  }
                />
              </label>
              )}
              {((draftCode === "slot_forbidden" && draft.scope === "全局") ||
                draftCode === "slot_teacher_role_required") && (
                <label>
                  <span className="rule-group-field-label">作用范围</span>
                  <ReadonlyValue
                    value={
                      draftCode === "slot_teacher_role_required"
                        ? "全年级各班 · 本班班主任"
                        : "全年级所有班级"
                    }
                  />
                </label>
              )}
              {showDaytimeParityLegs && (
                <>
                  <label>
                    <span className="rule-group-field-label">
                      单周学科组
                      <Tooltip title="这些学科只能落在单周；与双周组同一课位对腿，组内谁跟谁不规定">
                        <span className="rule-group-help">?</span>
                      </Tooltip>
                    </span>
                    <Select
                      mode="multiple"
                      showSearch
                      allowClear
                      value={draft.parityOddSubjects || []}
                      onChange={(values: string[]) => {
                        const odds = values || [];
                        const evens = draft.parityEvenSubjects || [];
                        setDraft((current) => ({
                          ...current,
                          parityOddSubjects: odds,
                          target: [...odds, ...evens].join(" / "),
                        }));
                        setDirty(true);
                      }}
                      options={allowedSubjectOptions.map((value) => ({
                        value,
                        label: value,
                      }))}
                      placeholder="如：化学、生物"
                    />
                  </label>
                  <label>
                    <span className="rule-group-field-label">
                      双周学科组
                      <Tooltip title="这些学科只能落在双周；与单周组同一课位对腿，组内谁跟谁不规定">
                        <span className="rule-group-help">?</span>
                      </Tooltip>
                    </span>
                    <Select
                      mode="multiple"
                      showSearch
                      allowClear
                      value={draft.parityEvenSubjects || []}
                      onChange={(values: string[]) => {
                        const evens = values || [];
                        const odds = draft.parityOddSubjects || [];
                        setDraft((current) => ({
                          ...current,
                          parityEvenSubjects: evens,
                          target: [...odds, ...evens].join(" / "),
                        }));
                        setDirty(true);
                      }}
                      options={allowedSubjectOptions.map((value) => ({
                        value,
                        label: value,
                      }))}
                      placeholder="如：历史、地理"
                    />
                  </label>
                </>
              )}
              {showRequiredTeacherRole && (
                <label>
                  <span className="rule-group-field-label">
                    安排角色
                    <Tooltip title="指定该课位必须由哪类教师承担，班主任会从班级管理中的配置读取">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Select
                    value={draft.requiredTeacherRole || "head_teacher"}
                    onChange={(value: "head_teacher") =>
                      updateDraft("requiredTeacherRole", value)
                    }
                    options={[{ value: "head_teacher", label: "班主任" }]}
                  />
                </label>
              )}
              {!showSlotPattern && !showPreferEarly && (
              <label>
                <span className="rule-group-field-label">
                  规则动作
                  <Tooltip title="由规则类别决定，不可手改；保存时会同步规则计算类型">
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <ReadonlyValue value={draft.operator} empty="未设置动作" />
              </label>
              )}
              {showRelation && (
                <label>
                  <span className="rule-group-field-label">
                    条件关系
                    <Tooltip title="说明多个条件之间如何组合，例如且、或、互斥、相邻">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Select
                    value={draft.relation}
                    onChange={(value) => updateDraft("relation", value)}
                    options={[
                      "无",
                      "且",
                      "或",
                      "互斥",
                      "相邻",
                      "同一晚课格",
                      "按学科分别执行",
                    ].map((value) => ({ value, label: value }))}
                  />
                </label>
              )}
              {showSpecificSlots ? (
                <div className="rule-group-form-wide">
                  <SpecificSlotEditor
                    value={draft.specificSlots}
                    weekdays={configuredWeekdayOptions}
                    periods={configuredPeriodOptions}
                    onChange={(specificSlots) =>
                      updateDraft("specificSlots", specificSlots)
                    }
                  />
                </div>
              ) : (
                <>
                  {showWeekdayFields && (
                    <label>
                      <span className="rule-group-field-label">
                        星期
                        <Tooltip
                          title={
                            draft.scope === "课位"
                              ? "课位规则的星期由模板固定，不可手改"
                              : draftCode === "subject_daytime_parity_pair"
                              ? "对课只作用在勾选的星期，可多选：周一、周二、周六都可以，不限周六。"
                              : "选择规则生效的星期，可以多选；选择具体课位后会自动带出"
                          }
                        >
                          <span className="rule-group-help">?</span>
                        </Tooltip>
                      </span>
                      {draft.scope === "课位" ? (
                        <ReadonlyValue values={weekdaySelections(draft.weekday)} />
                      ) : (
                        <Select
                          mode="multiple"
                          showSearch
                          maxTagCount="responsive"
                          value={weekdaySelections(draft.weekday)}
                          onChange={(value: string[]) =>
                            updateDraft(
                              "weekday",
                              value.length ? value.join("、") : "未指定",
                            )
                          }
                          options={configuredWeekdayOptions.map((value) => ({
                            value,
                            label: value,
                          }))}
                          placeholder="请选择星期（可多选）"
                        />
                      )}
                    </label>
                  )}
                  {showPeriodField && (
                    <label>
                      <span className="rule-group-field-label">
                        {showPreferEarly ? "尽量安排的节次" : "节次"}
                        <Tooltip
                          title={
                            showPreferEarly
                              ? "主科优先排进这些节次；下面可设每个班每门课允许多少节排在这些节次之外"
                              : draft.scope === "课位"
                              ? "课位规则的节次由模板固定，不可手改"
                              : "选择已配置的具体课位节次，可多选；课位规则会自动带出"
                          }
                        >
                          <span className="rule-group-help">?</span>
                        </Tooltip>
                      </span>
                      {draft.scope === "课位" ? (
                        <ReadonlyValue values={periodSelections(draft.period)} />
                      ) : (
                        <Select
                          mode="multiple"
                          showSearch
                          maxTagCount="responsive"
                          value={periodSelections(draft.period)}
                          onChange={(value: string[]) =>
                            updateDraft(
                              "period",
                              value.length ? value.join("、") : UNRESOLVED_PERIOD,
                            )
                          }
                          options={configuredPeriodOptions.map((value) => ({
                            value,
                            label: value,
                          }))}
                          placeholder={
                            showPreferEarly
                              ? "请选择尽量安排的节次"
                              : "请选择具体节次（可多选）"
                          }
                        />
                      )}
                    </label>
                  )}
                  {showSelfStudyDayConfig && (
                    <label>
                      <span className="rule-group-field-label">
                        自习日选择数量
                        <Tooltip title="从上面选择的候选星期中，要求第8、9节至少有几天保持自习（与晚自习无关）">
                          <span className="rule-group-help">?</span>
                        </Tooltip>
                      </span>
                      <Space.Compact block>
                        <InputNumber
                          min={1}
                          max={weekdaySelections(draft.weekday).length || 1}
                          value={draft.choiceCount || 1}
                          onChange={(value) => {
                            updateDraft("choiceCount", value || 1);
                            updateDraft("quantity", `${value || 1}天`);
                          }}
                        />
                        <span className="rule-group-unit-suffix">天</span>
                      </Space.Compact>
                    </label>
                  )}
                </>
              )}
              {showAllowedSubjects && (
                <div className="rule-group-form-wide rule-group-form-field">
                  <span className="rule-group-field-label">
                    允许科目
                    <Tooltip title="选择该班级在指定星期和节次内允许安排的科目，可多选">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Select
                    mode="multiple"
                    maxTagCount="responsive"
                    value={draft.allowedSubjects || []}
                    onChange={(value: string[]) => {
                      setDraft((current) => ({
                        ...current,
                        allowedSubjects: value,
                        quantity: value.length
                          ? `仅${value.join(" / ")}`
                          : "未配置允许科目",
                      }));
                      setDirty(true);
                    }}
                    options={allowedSubjectOptions.map((value) => ({
                      value,
                      label: value,
                    }))}
                    placeholder="请选择允许科目"
                  />
                </div>
              )}
              {!showSlotPattern && !showPreferEarly && (
              <label>
                <span className="rule-group-field-label">
                  周期
                  <Tooltip title="说明规则按每周、单周、双周还是单双周配对执行">
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <Select
                  value={draft.cycle}
                  onChange={(value) => updateDraft("cycle", value)}
                  options={(draft.kind === "配对"
                    ? ["每周", "单周", "双周", "单周 / 双周"]
                    : ["每周", "单周", "双周"]
                  ).map((value) => ({ value, label: value }))}
                />
              </label>
              )}
              {showPreferEarly && (
                <label>
                  <span className="rule-group-field-label">
                    允许不在这些节次
                    <Tooltip title="每个班、每门所选主科，全周最多几节可以排在勾选节次之外。0 表示都必须落在所选节次。软目标时超出只加分，硬约束时超出则无解。">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Space.Compact block>
                    <span className="rule-group-unit-prefix">最多</span>
                    <InputNumber
                      min={0}
                      max={20}
                      value={
                        draft.maxOutsidePreferred ??
                        Number(draft.quantitySpec?.amount) ??
                        2
                      }
                      onChange={(value) => {
                        const amount = Math.max(0, Number(value) || 0);
                        setDraft((current) => ({
                          ...current,
                          maxOutsidePreferred: amount,
                          quantity: `允许 ${amount} 节不在所选节次`,
                          quantitySpec: {
                            amount,
                            unit: "section",
                            distribution: "none",
                          },
                        }));
                        setDirty(true);
                      }}
                    />
                    <span className="rule-group-unit-suffix">节</span>
                  </Space.Compact>
                </label>
              )}
              {showSlotTeacherBalanceCap && (
                <label>
                  <span className="rule-group-field-label">
                    目标
                    <Tooltip title="指定节次上，每名任课教师每周最多承担的节数；保存后写入排课约束 max_per_teacher">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Space.Compact block>
                    <span className="rule-group-unit-prefix">每人最多</span>
                    <InputNumber
                      min={1}
                      max={20}
                      value={slotTeacherBalanceCap(draft)}
                      onChange={handleSlotTeacherBalanceCapChange}
                    />
                    <span className="rule-group-unit-suffix">节</span>
                  </Space.Compact>
                </label>
              )}
              {showPeriodMinimumAmount && (
                <label>
                  <span className="rule-group-field-label">
                    课时下限
                    <Tooltip title="所选教师在勾选的星期×节次集合中，全周合计至少安排这么多节（不必同一天）">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <Space.Compact block>
                    <span className="rule-group-unit-prefix">合计至少</span>
                    <InputNumber
                      min={1}
                      max={40}
                      value={
                        Number(draft.quantitySpec?.amount) ||
                        Number(String(draft.quantity || "").match(/\d+/)?.[0]) ||
                        2
                      }
                      onChange={(value) => {
                        const amount = Number(value) || 1;
                        setDraft((current) => ({
                          ...current,
                          quantity: `至少 ${amount} 节`,
                          quantitySpec: {
                            amount,
                            unit: "section",
                            distribution: "none",
                          },
                        }));
                        setDirty(true);
                      }}
                    />
                    <span className="rule-group-unit-suffix">节</span>
                  </Space.Compact>
                </label>
              )}
              {showConsecutive && (
                <div className="rule-group-form-field">
                  <span className="rule-group-field-label">
                    {showTeacherConsecutive ? "教师连堂要求" : "学科连堂要求"}
                    <Tooltip title={showTeacherConsecutive ? "教师连堂可以选择同一班连续授课，或在相邻课节切换到另一个班。" : "每周至少有多少天出现连续若干节该学科；节次按整天白天课统计，无需再选具体节次"}>
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <div className="rule-group-distribution-grid">
                    {showTeacherConsecutive && (
                      <label>
                        <span>连堂范围</span>
                        <Select
                          value={draft.distributionSpec?.teacherClassMode || "same_class"}
                          options={[
                            { value: "same_class", label: "同一班连堂" },
                            { value: "cross_class", label: "跨班连堂" },
                          ]}
                          onChange={(value) =>
                            handleDistributionChange({
                              target: "consecutive",
                              teacherClassMode: value,
                              consecutiveLength: draft.distributionSpec?.consecutiveLength || 2,
                              minimumDays: draft.distributionSpec?.minimumDays || 1,
                            })
                          }
                        />
                      </label>
                    )}
                    <label>
                      <span>连续长度</span>
                      <Space.Compact block>
                        <InputNumber
                          min={2}
                          max={9}
                          value={draft.distributionSpec?.consecutiveLength || 2}
                          onChange={(value) =>
                            handleDistributionChange({
                              target: "consecutive",
                              consecutiveLength: value || 2,
                              minimumDays:
                                draft.distributionSpec?.minimumDays || 1,
                            })
                          }
                        />
                        <span className="rule-group-unit-suffix">节</span>
                      </Space.Compact>
                    </label>
                    <label>
                      <span>每周至少</span>
                      <Space.Compact block>
                        <InputNumber
                          min={1}
                          max={7}
                          value={draft.distributionSpec?.minimumDays || 1}
                          onChange={(value) =>
                            handleDistributionChange({
                              target: "consecutive",
                              consecutiveLength:
                                draft.distributionSpec?.consecutiveLength || 2,
                              minimumDays: value || 1,
                            })
                          }
                        />
                        <span className="rule-group-unit-suffix">天</span>
                      </Space.Compact>
                    </label>
                  </div>
                </div>
              )}
              {showSlotPattern && (
                <div className="rule-group-form-wide rule-group-form-field">
                  <span className="rule-group-field-label">课位与组合</span>
                  <SlotPatternEditor
                    subjects={draft.target}
                    weekdayOptions={configuredWeekdayOptions}
                    periodOptions={configuredPeriodOptions}
                    spec={draft.distributionSpec}
                    onChange={({ distributionSpec, weekday, period }) => {
                      setDraft((current) => ({
                        ...current,
                        distributionSpec,
                        weekday,
                        period,
                      }));
                      setDirty(true);
                    }}
                  />
                </div>
              )}
              {showDistribution && (
                <div className="rule-group-form-field">
                  <span className="rule-group-field-label">
                    排课目标
                    <Tooltip title="课时数量从课时管理读取；这里仅配置连堂、均衡分布或教师负荷目标">
                      <span className="rule-group-help">?</span>
                    </Tooltip>
                  </span>
                  <DistributionTargetEditor
                    family={draftFamily}
                    spec={draft.distributionSpec}
                    onChange={handleDistributionChange}
                  />
                </div>
              )}
              {!showSlotPattern && (
              <div className="rule-group-form-wide rule-group-generated-summary">
                <span className="rule-group-field-label">
                  规则摘要
                  <Tooltip title="根据规则类别、对象、动作和课位字段自动生成，排课算法使用结构化字段而不是这段文字">
                    <span className="rule-group-help">?</span>
                  </Tooltip>
                </span>
                <p>{buildRuleSummary(draft)}</p>
                <small>
                  课时数量由课时管理统一提供；摘要仅用于确认规则含义，不作为排课条件。
                </small>
              </div>
              )}
              {!showSlotPattern && <RuleImpactPreview rule={draft} gridConfig={gridConfig} />}
            </div>
            <div className="rule-group-priority">
              <span>优先级</span>
              <Button
                type={draft.priority === "hard" ? "primary" : "default"}
                onClick={() => updateDraft("priority", "hard")}
              >
                硬约束 · 必须满足
              </Button>
              <Button
                type={draft.priority === "soft" ? "primary" : "default"}
                onClick={() => updateDraft("priority", "soft")}
              >
                软目标 · 尽量满足
              </Button>
              <Tag
                className={`rule-group-enabled-tag${draft.enabled ? " is-on" : ""}`}
                color={draft.enabled ? "green" : "default"}
              >
                {draft.enabled ? "已启用" : "已停用"}
              </Tag>
              <Button
                size="small"
                type={draft.enabled ? "default" : "primary"}
                onClick={() => {
                  const next = !draft.enabled;
                  updateDraft("enabled", next);
                  message.warning(
                    next
                      ? "已改为启用，请再点右下角「保存规则」才会生效"
                      : "已改为停用，请再点右下角「保存规则」才会生效",
                  );
                }}
              >
                {draft.enabled ? "停用" : "启用"}
              </Button>
              {dirty ? (
                <small className="rule-group-save-hint">未保存，关闭会丢失</small>
              ) : null}
            </div>
            <div className="rule-group-editor-actions">
              <Button danger onClick={deleteRule}>
                删除明细
              </Button>
              <Space>
                <Button onClick={() => setOpen(false)}>取消</Button>
                <Button type="primary" onClick={saveDraft}>
                  保存规则
                </Button>
              </Space>
            </div>
          </section>
          <aside className="rule-group-audit">
            <div className="rule-group-sidebar-head">
              <span>PRECHECK</span>
              <strong>排课前审计</strong>
            </div>
            <div className="rule-group-audit-stats">
              <div>
                <span>已启用</span>
                <strong>{enabledRules.length}</strong>
              </div>
              <div>
                <span>硬约束</span>
                <strong>{hardCount}</strong>
              </div>
              <div>
                <span>软目标</span>
                <strong>{softCount}</strong>
              </div>
              <div>
                <span>待解析</span>
                <strong>{unresolvedCount}</strong>
              </div>
            </div>
            <p className="rule-group-audit-process-empty" style={{ marginTop: 14 }}>
              生成失败时的求解过程与优化建议在独立的「排课诊断」侧栏中查看，不会占用本工作台。
            </p>
            <div className="rule-group-audit-note">
              <strong>规则组范围</strong>
              <span>
                {ruleGroupScopeLabel(group, grades, resources?.classes || [])}
              </span>
              <span>{group.term}</span>
            </div>
          </aside>
        </div>
      </Modal>
    </div>
  );
}
