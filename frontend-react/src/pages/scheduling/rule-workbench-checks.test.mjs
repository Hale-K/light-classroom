import test from 'node:test'
import assert from 'node:assert/strict'
import { inspectRuleConfiguration, ruleWeekParity } from './rule-workbench-checks.ts'

const rule = (id, code, changes = {}) => ({ id, title: id, code, enabled: true, priority: 'hard',
  target: { type: 'subject', ids: [1] }, weekdays: [5], periods: [7], period_scope: 'regular',
  week_parity: 'all', schedule_scope: 'all', params: {}, ...changes })
const slots = [{ weekday: 5, period: 7, week_parity: 'odd', kind: 'regular' },
  { weekday: 5, period: 7, week_parity: 'even', kind: 'regular' }]

test('disabled teacher rules explain account state and retain the blocking check', () => {
  const issues = inspectRuleConfiguration([rule('R12', 'manual_review', {
    title: '毛宇莹不可用课位', params: { disabled_teacher_names: ['毛宇莹'] },
  })], slots)
  const issue = issues.find(item => item.kind === 'incomplete')
  assert.equal(issue.level, 'error')
  assert.match(issue.message, /毛宇莹账号已停用/)
  assert(!issue.message.includes('尚未识别'))
  assert(issue.suggestions.some(text => text.includes('人员账号')))
})

test('single and alternating week choices keep their actual parity', () => {
  assert.equal(ruleWeekParity('单周'), 'odd')
  assert.equal(ruleWeekParity('双周'), 'even')
  assert.equal(ruleWeekParity('每周'), 'all')
  assert.equal(ruleWeekParity('单周 / 双周'), 'all')
})

test('reports a subject with all allowed slots forbidden, identifying both rules', () => {
  const issues = inspectRuleConfiguration([rule('allow', 'subject_allowed_slots'), rule('ban', 'slot_forbidden')], slots)
  assert(issues.some(issue => issue.level === 'error' && issue.ruleIds.includes('allow') && issue.ruleIds.includes('ban')))
})

test('different subjects, timetable scopes and parity do not cause false conflicts', () => {
  const allowed = rule('allow', 'subject_allowed_slots', { week_parity: 'odd', schedule_scope: 'admin' })
  for (const changes of [{ target: { type: 'subject', ids: [2] } }, { schedule_scope: 'walk' }, { week_parity: 'even' }, { enabled: false }, { priority: 'soft' }]) {
    assert.equal(inspectRuleConfiguration([allowed, rule('ban', 'slot_forbidden', changes)], slots).filter(i => i.level === 'error').length, 0)
  }
})

test('multi-target restrictions detect a contradiction for just one selected subject', () => {
  const issues = inspectRuleConfiguration([rule('allow', 'subject_allowed_slots', { target: { type: 'subject', ids: [1, 2] } }), rule('ban', 'slot_forbidden')], slots)
  assert(issues.some(i => i.level === 'error' && i.ruleIds.includes('ban')))
})

test('overlapping allowed rules use the intersection and global bans apply', () => {
  assert(inspectRuleConfiguration([rule('a', 'subject_allowed_slots'), rule('b', 'subject_allowed_slots', { weekdays: [4] })], slots).some(i => i.level === 'error'))
  assert(inspectRuleConfiguration([rule('a', 'subject_allowed_slots'), rule('b', 'slot_forbidden', { target: { type: 'global', ids: [] } })], slots).some(i => i.level === 'error'))
})

test('duplicates are suggestions; impossible consecutive days are errors', () => {
  assert(inspectRuleConfiguration([rule('a', 'slot_forbidden'), rule('b', 'slot_forbidden')], slots).some(i => i.level === 'warning'))
  assert(inspectRuleConfiguration([rule('c', 'subject_consecutive', { params: { minimum_days: 2, minimum_block_length: 2 } })], slots).some(i => i.level === 'error'))
})

test('missing grid does not imply no available slots; unparsed rules remain visible', () => {
  assert.equal(inspectRuleConfiguration([rule('a', 'subject_allowed_slots')], undefined).length, 0)
  assert(inspectRuleConfiguration([rule('a', 'manual_review')], undefined).some(i => i.level === 'error'))
})

test('two teacher ban entrances are the same responsibility, ignoring authoring metadata', () => {
  const issues = inspectRuleConfiguration([
    rule('a', 'slot_forbidden', { target: {type:'teacher',ids:[11]}, params:{source_operator:'禁止排课'} }),
    rule('b', 'teacher_forbidden_slots', { target: {type:'teacher',ids:[11]}, params:{forbidden_slots:[{weekday:5,periods:[7]}]} }),
  ], slots)
  assert(issues.some(i => i.kind === 'duplicate' && i.ruleIds.length === 2 && i.suggestions.length))
  assert(!issues.some(i => i.level === 'error'))
})

test('compatible overlapping bans and stricter daily limits are explained, not blocked', () => {
  const wideSlots = [...slots, ...slots.map(s=>({...s,period:6}))]
  const issues = inspectRuleConfiguration([
    rule('a','slot_forbidden',{periods:[6,7]}), rule('b','slot_forbidden'),
    rule('c','teacher_daily_limit',{target:{type:'teacher',ids:[11]},params:{max_lessons_per_day:4}}),
    rule('d','teacher_daily_limit',{target:{type:'teacher',ids:[11]},params:{max_lessons_per_day:3}}),
  ], wideSlots)
  assert(issues.some(i=>i.kind==='redundant'))
  assert(issues.some(i=>i.kind==='overlap' && /3/.test(i.message)))
  assert(!issues.some(i=>i.level==='error'))
})

const resources = {teachers:[{id:11,name:'王老师'}],subjects:[{id:1,name:'数学'}],
  classes:[{id:101,name:'高一（1）班',grade_id:1,head_teacher_id:11}],
  assignments:[{id:1,class_id:101,subject_id:1,teacher_id:11,weekly_periods:5}]}

test('subject allow-list crosses teacher bans via actual teaching assignments', () => {
  const issues = inspectRuleConfiguration([rule('a','subject_allowed_slots'),
    rule('b','teacher_forbidden_slots',{target:{type:'teacher',ids:[11]}})], slots, resources)
  const conflict = issues.find(i=>i.level==='error')
  assert(conflict.ruleIds.includes('a') && conflict.ruleIds.includes('b'))
  assert.match(conflict.message,/高一（1）班.*数学.*王老师/)
  assert(conflict.context && conflict.suggestions.length)
  assert.equal(inspectRuleConfiguration([rule('a','subject_allowed_slots'),
    rule('b','teacher_forbidden_slots',{target:{type:'teacher',ids:[12]}})], slots, resources).filter(i=>i.level==='error').length,0)
})

test('class-only subject restrictions can eliminate an assigned subject allow-list', () => {
  assert(inspectRuleConfiguration([rule('a','subject_allowed_slots'),
    rule('b','class_allowed_subjects',{target:{type:'class',ids:[101]},params:{allowed_subject_ids:[2]}})],slots,resources)
    .some(i=>i.level==='error' && i.ruleIds.includes('b')))
})

test('mandatory full class slots conflict with bans, but trailing-empty does not demand full slots', () => {
  const noGap=rule('full','class_gap_free',{target:{type:'class',ids:[101]}})
  const ban=rule('ban','slot_forbidden',{target:{type:'class',ids:[101]}})
  assert(inspectRuleConfiguration([noGap,ban],slots,resources).some(i=>i.level==='error' && i.ruleIds.includes('ban')))
  assert(!inspectRuleConfiguration([{...noGap,params:{trailing_empty:true}},ban],slots,resources).some(i=>i.level==='error'))
})

test('headteacher required slots identify the actual teacher unavailability', () => {
  assert(inspectRuleConfiguration([rule('role','slot_teacher_role_required',{target:{type:'global',ids:[]}}),
    rule('ban','teacher_forbidden_slots',{target:{type:'teacher',ids:[11]}})],slots,resources)
    .some(i=>i.level==='error' && i.ruleIds.includes('role') && i.ruleIds.includes('ban')))
})

test('minimum lessons and consecutive length respect available slots and daily caps', () => {
  const target={type:'teacher',ids:[11]}
  const cap=rule('cap','teacher_daily_limit',{target,params:{max_lessons_per_day:1}})
  assert(inspectRuleConfiguration([cap,rule('min','teacher_period_minimum',{target,params:{minimum_lessons:2}})],slots)
    .some(i=>i.level==='error' && i.ruleIds.includes('cap') && i.ruleIds.includes('min')))
  const wide=[...slots,...slots.map(s=>({...s,period:8}))]
  assert(inspectRuleConfiguration([cap,rule('con','teacher_consecutive',{target,periods:[7,8],params:{minimum_days:1,minimum_block_length:2}})],wide)
    .some(i=>i.level==='error' && i.ruleIds.includes('cap') && i.ruleIds.includes('con')))
})

test('soft conflicts are suggestions, and admin assignment links do not invent walk-class conflicts', () => {
  const a=rule('a','subject_allowed_slots')
  const b=rule('b','teacher_forbidden_slots',{target:{type:'teacher',ids:[11]},priority:'soft'})
  assert(inspectRuleConfiguration([a,b],slots,resources).some(i=>i.level==='warning' && i.kind==='conflict'))
  assert(!inspectRuleConfiguration([{...a,schedule_scope:'walk'},{...b,priority:'hard',schedule_scope:'walk'}],slots,resources).some(i=>i.level==='error'))
})

test('early-period preference with allowed exceptions is not an exclusive allow-list', () => {
  assert(!inspectRuleConfiguration([rule('early','subject_prefer_early_periods',{periods:[1],params:{max_outside:2}}),rule('ban','slot_forbidden')],slots).some(i=>i.level==='error'))
  assert(inspectRuleConfiguration([rule('early','subject_prefer_early_periods',{periods:[7],params:{max_outside:0}}),rule('ban','slot_forbidden')],slots).some(i=>i.level==='error'))
})

test('duplicate detection does not swap weekday and period axes', () => {
  const grid=[...slots,...slots.map(s=>({...s,weekday:7,period:5}))]
  assert(!inspectRuleConfiguration([rule('a','slot_forbidden'),rule('b','slot_forbidden',{weekdays:[7],periods:[5]})],grid).some(i=>i.kind==='duplicate'))
})

test('only-own-head-class bans do not incorrectly forbid the teachers other classes', () => {
  const context={...resources,classes:[...resources.classes,{id:102,name:'高一（2）班',grade_id:1,head_teacher_id:12}],assignments:[{...resources.assignments[0],class_id:102}]}
  assert(!inspectRuleConfiguration([rule('a','subject_allowed_slots'),rule('b','teacher_forbidden_slots',{target:{type:'teacher',ids:[11]},params:{own_head_class_only:true}})],slots,context).some(i=>i.level==='error'))
})

test('same-subject period preference and conditional fill have an explainable responsibility overlap', () => {
  const issues=inspectRuleConfiguration([rule('a','subject_prefer_early_periods',{periods:[1,2],params:{max_outside:2}}),rule('b','subject_gap_fill_late_periods',{periods:[8,9]})],slots)
  assert(issues.some(i=>i.kind==='overlap' && i.suggestions.length))
  assert(!issues.some(i=>i.kind==='duplicate' || i.level==='error'))
})
