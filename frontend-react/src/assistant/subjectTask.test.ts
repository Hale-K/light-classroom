import assert from 'node:assert/strict'
import test from 'node:test'
import { assertSubjectTaskSubmission, isSubjectCreationRequest, isSubjectChoiceReply, isSubjectTaskCancellation, readExplicitSubjectName, readPendingSubjectDraft, setActiveSubjectDraft } from './subjectTask.ts'

test('失败后的补充消息能够恢复明确提供的科目名称', () => {
  assert.equal(readExplicitSubjectName('帮我新增一个校本科目，名称叫“人工智能基础”。'), '人工智能基础')
  assert.equal(isSubjectChoiceReply('课程类型是活动课，不允许晚自习。'), true)
  assert.equal(isSubjectChoiceReply('帮我查询活动课'), false)
  assert.equal(readExplicitSubjectName('帮我新增科目'), null)
})

test('识别创建科目，不拦截生成课表和查询科目', () => {
  assert.equal(isSubjectCreationRequest('帮我新增一个科目'), true)
  assert.equal(isSubjectCreationRequest('生成一个科目叫心理'), true)
  assert.equal(isSubjectCreationRequest('科目名称：校本 科目类型：活动课 不允许参加晚自习资格'), true)
  assert.equal(isSubjectCreationRequest('科目名称: 校本 课程类型: 活动课 不允许晚自习'), true)
  assert.equal(isSubjectCreationRequest('生成课表'), false)
  assert.equal(isSubjectCreationRequest('按这些科目生成课表'), false)
  assert.equal(isSubjectCreationRequest('查询科目'), false)
})

test('刷新恢复待补充的草稿，损坏数据不执行', () => {
  const draft = { name: null, course_type: 'activity', evening_study_allowed: true }
  assert.deepEqual(readPendingSubjectDraft(JSON.stringify(draft)), draft)
  assert.equal(readPendingSubjectDraft('{broken'), null)
  assert.equal(readPendingSubjectDraft('{"name":"心理"}'), null)
  const partial = { name: '心理', course_type: null, evening_study_allowed: null }
  assert.deepEqual(readPendingSubjectDraft(JSON.stringify(partial)), partial)
})

test('缺少类型或晚自习资格时不能保存，明确不允许可以保存', () => {
  const incomplete = { name: '心理', course_type: null, evening_study_allowed: null }
  const release = setActiveSubjectDraft(incomplete)
  try { assert.throws(() => assertSubjectTaskSubmission(incomplete, false)) }
  finally { release() }
})

test('允许取消补充信息，不误判科目名称', () => {
  assert.equal(isSubjectTaskCancellation('取消'), true)
  assert.equal(isSubjectTaskCancellation('心理'), false)
})

test('自动操作只能保存已校验数据，不能修改已有科目', () => {
  const draft = { name: '心理', course_type: 'subject' as const, evening_study_allowed: false }
  const release = setActiveSubjectDraft(draft)
  try {
    assert.doesNotThrow(() => assertSubjectTaskSubmission(draft, false))
    assert.throws(() => assertSubjectTaskSubmission({ ...draft, name: '数学' }, false))
    assert.throws(() => assertSubjectTaskSubmission({ ...draft, evening_study_allowed: true }, false))
    assert.throws(() => assertSubjectTaskSubmission(draft, true))
  } finally { release() }
  assert.doesNotThrow(() => assertSubjectTaskSubmission({ ...draft, name: '其他' }, false))
})

test('旧任务结束不能清除新任务的保存校验', () => {
  const first = setActiveSubjectDraft({ name: '心理', course_type: 'subject', evening_study_allowed: false })
  const second = setActiveSubjectDraft({ name: '编程', course_type: 'subject', evening_study_allowed: false })
  first()
  assert.throws(() => assertSubjectTaskSubmission({ name: '心理', course_type: 'subject', evening_study_allowed: false }, false))
  second()
})
