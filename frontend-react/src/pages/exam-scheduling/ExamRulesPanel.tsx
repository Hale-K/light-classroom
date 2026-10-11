import { InputNumber, Switch, Tag, Tooltip } from 'antd'
import type { ExamRules } from '@/types'

export const DEFAULT_EXAM_RULES: ExamRules = { student_daily_limit: 4, min_break_minutes: 0, teacher_daily_limit: 4, avoid_own_subject: false, same_subject_same_time: false }

export default function ExamRulesPanel({ value, onChange }: { value?: ExamRules; onChange: (value: ExamRules) => void }) {
  const rules = { ...DEFAULT_EXAM_RULES, ...value }
  const update = (patch: Partial<ExamRules>) => onChange({ ...rules, ...patch })
  return <div className="es-rules">
    <div className="es-rule-section"><h3>考试时间</h3>
      <label className="es-rule-row"><span>每天最多考几门</span><span><InputNumber aria-label="每天最多考几门" min={1} max={4} value={rules.student_daily_limit} onChange={n => update({ student_daily_limit: n ?? 4 })} /> 门</span></label>
      <label className="es-rule-row"><span>两场考试至少间隔</span><span><InputNumber aria-label="两场考试至少间隔" min={0} max={180} step={5} value={rules.min_break_minutes} onChange={n => update({ min_break_minutes: n ?? 0 })} /> 分钟</span></label>
      <div className="es-rule-row"><span>同科目各年级同时考</span><Switch aria-label="同科目各年级同时考" checked={rules.same_subject_same_time} onChange={b => update({ same_subject_same_time: b })} /></div>
      <Tooltip title="选科同步排考时，允许同科目分两批考试，让不同选科组合的学生连续考完。需配套分批试卷。"><div className="es-rule-row"><span>允许同科目分批</span><Switch aria-label="允许同科目分批" checked={rules.allow_subject_batches || false} onChange={b => update({ allow_subject_batches: b })} /></div></Tooltip>
    </div>
    <div className="es-rule-section"><h3>监考要求</h3>
      <Tooltip title="包含当天其他考试的监考任务"><label className="es-rule-row"><span>每位教师每天最多监考</span><span><InputNumber aria-label="每位教师每天最多监考" min={1} max={8} value={rules.teacher_daily_limit} onChange={n => update({ teacher_daily_limit: n ?? 4 })} /> 场</span></label></Tooltip>
      <Tooltip title="教师不监考自己任教年级的学科"><div className="es-rule-row"><span>任教学科回避</span><Switch aria-label="任教学科回避" checked={rules.avoid_own_subject} onChange={b => update({ avoid_own_subject: b })} /></div></Tooltip>
      <div className="es-rule-row"><span>尽量均衡监考工作量</span><Tag color="blue">自动优化</Tag></div>
    </div>
    <div className="es-rule-section"><h3>考生与资源</h3>{rules.room_mode === 'gaokao' && <p className="es-muted">高考模拟：每场最多{rules.room_seat_limit || 30}人，分科设场、打散座次、至少2名监考。</p>}<div className="es-rule-tags"><Tag>考生考试不重叠</Tag><Tag>人员与考场不重复占用</Tag><Tag>座位不超容量</Tag><Tag>遵守教师可用时间</Tag></div><p className="es-muted">基础检查自动执行。参考范围、考场和教师在准备步骤中选择。</p></div>
  </div>
}
