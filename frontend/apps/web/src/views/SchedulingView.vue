<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { schedulingApi } from '@zhiheng/api'
import type { ScheduleEntry, ScheduleStaffingIssue, SchedulingResources, ScheduleStrategyOption, ScheduleValidationIssue } from '@zhiheng/shared'
import Icon from '@/components/Icon.vue'
import ScheduleGrid from '@/components/ScheduleGrid.vue'

const now = new Date()
const schoolYear = now.getMonth() >= 7 ? now.getFullYear() : now.getFullYear() - 1
const monday = new Date(now)
monday.setDate(now.getDate() - ((now.getDay() + 6) % 7))
const localDateValue = (value: Date) => [
  value.getFullYear(),
  String(value.getMonth() + 1).padStart(2, '0'),
  String(value.getDate()).padStart(2, '0'),
].join('-')

const loading = ref(false)
const generating = ref(false)
const generationStage = ref<'idle' | 'validating' | 'generating' | 'refreshing' | 'done' | 'blocked' | 'error'>('idle')
const failedStageIndex = ref(0)
const validationIssues = ref<ScheduleValidationIssue[]>([])
const staffingIssues = ref<ScheduleStaffingIssue[]>([])
const generationSummary = ref('')
const activeTab = ref('weekly')
const resources = ref<SchedulingResources>({ teachers: [], subjects: [], classes: [], assignments: [] })
const strategyOptions = ref<ScheduleStrategyOption[]>([])
const weekly = ref<ScheduleEntry[]>([])
const calendar = ref<ScheduleEntry[]>([])
const selectedClassId = ref<number>()
const academicYear = ref(`${schoolYear}-${schoolYear + 1}`)
const term = ref(now.getMonth() >= 1 && now.getMonth() < 7 ? '2' : '1')
const weekStart = ref(localDateValue(monday))
const assignmentVisible = ref(false)
const teacherVisible = ref(false)
const conditionVisible = ref(false)
const assignmentForm = reactive({ teacher_id: undefined as number | undefined, subject_id: undefined as number | undefined, class_id: undefined as number | undefined, weekly_periods: 4, room: '' })
const teacherForm = reactive({ name: '', phone: '', password: '123456' })
const conditions = reactive({
  max_class_lessons_per_day: 7,
  max_teacher_lessons_per_day: 6,
  max_same_subject_per_day: 1,
  forbidden_slots: [] as string[],
  strategy_codes: ['daily_balance', 'cross_day_variety', 'random_tiebreak'] as string[],
})
const weekdayNames = ['周一', '周二', '周三', '周四', '周五']
const slotOptions = Array.from({ length: 5 }, (_, day) => Array.from({ length: 8 }, (_, period) => ({
  value: `${day + 1}-${period + 1}`,
  label: `${weekdayNames[day]} 第 ${period + 1} 节`,
}))).flat()

const selectedClassName = computed(() => resources.value.classes.find((item) => item.id === selectedClassId.value)?.name || '请选择班级')
const currentEntries = computed(() => activeTab.value === 'calendar' ? calendar.value : weekly.value)
const visibleAssignments = computed(() => resources.value.assignments.filter((item) => (
  item.academic_year === academicYear.value && item.term === term.value && item.class_id === selectedClassId.value
)))
const selectedStrategyNames = computed(() => conditions.strategy_codes.map(
  code => strategyOptions.value.find(option => option.code === code)?.name || code,
).join(' → '))
const generationSteps = [
  { code: 'validating', label: '校验资源' },
  { code: 'generating', label: '初排与冲突修复' },
  { code: 'refreshing', label: '保存并刷新' },
  { code: 'done', label: '生成完成' },
] as const
const generationStepIndex = computed(() => {
  const index = generationSteps.findIndex(item => item.code === generationStage.value)
  return index >= 0 ? index : failedStageIndex.value
})

function generationPayload() {
  return {
    academic_year: academicYear.value,
    term: term.value,
    days: 5,
    periods_per_day: 8,
    max_class_lessons_per_day: conditions.max_class_lessons_per_day,
    max_teacher_lessons_per_day: conditions.max_teacher_lessons_per_day,
    max_same_subject_per_day: conditions.max_same_subject_per_day,
    forbidden_slots: conditions.forbidden_slots.map((slot) => slot.split('-').map(Number) as [number, number]),
    strategy_codes: conditions.strategy_codes,
    random_seed: Math.floor(Math.random() * 2_147_483_647),
  }
}

function issueText(issue: ScheduleValidationIssue) {
  if (issue.entity_type === 'teacher') {
    const name = resources.value.teachers.find(item => item.id === issue.entity_id)?.name || `教师 ${issue.entity_id}`
    return `${name}承担 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
  }
  const className = resources.value.classes.find(item => item.id === issue.entity_id)?.name || `班级 ${issue.entity_id}`
  if (issue.entity_type === 'class_subject') {
    const subjectName = resources.value.subjects.find(item => item.id === issue.related_id)?.name || '该学科'
    return `${className}的${subjectName}需要 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
  }
  return `${className}需要 ${issue.requested} 节，当前条件最多可排 ${issue.capacity} 节`
}

function staffingIssueText(issue: ScheduleStaffingIssue) {
  const weekday = weekdayNames[issue.weekday - 1] || `星期${issue.weekday}`
  return `${issue.class_name || `班级 ${issue.class_id}`} ${weekday}第 ${issue.gap_period} 节：${issue.teacher_name || '任课教师'}正在${issue.blocking_class_name || `班级 ${issue.blocking_class_id}`}上${issue.subject_name || '该学科'}，建议增配 1 名${issue.subject_name || '该学科'}教师或调整任教关系`
}

async function loadResources() {
  ;[resources.value, strategyOptions.value] = await Promise.all([
    schedulingApi.resources(),
    schedulingApi.strategies(),
  ])
  selectedClassId.value ||= resources.value.classes[0]?.id
}

async function loadTable() {
  if (!selectedClassId.value) return
  if (!generating.value) loading.value = true
  try {
    weekly.value = await schedulingApi.weekly({ class_id: selectedClassId.value, academic_year: academicYear.value, term: term.value })
    calendar.value = await schedulingApi.calendar({ class_id: selectedClassId.value, academic_year: academicYear.value, term: term.value, week_start: weekStart.value })
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '课表加载失败')
  } finally { if (!generating.value) loading.value = false }
}

async function generateAll() {
  if (!conditions.strategy_codes.length) return ElMessage.warning('请至少选择一种排课策略')
  generating.value = true
  generationStage.value = 'validating'
  failedStageIndex.value = 0
  validationIssues.value = []
  staffingIssues.value = []
  generationSummary.value = '正在核对班级课时、教师负荷和禁排条件'
  try {
    const payload = generationPayload()
    const validation = await schedulingApi.validate(payload)
    if (!validation.valid) {
      validationIssues.value = validation.issues
      generationStage.value = 'blocked'
      generationSummary.value = `发现 ${validation.issues.length} 项无解条件，请调整后重新生成`
      ElMessage.warning('排课条件校验未通过')
      return
    }
    generationStage.value = 'generating'
    failedStageIndex.value = 1
    generationSummary.value = `正在为 ${validation.assignment_count} 条任教关系安排 ${validation.requested_lessons} 节课`
    const result = await schedulingApi.generate(payload)
    staffingIssues.value = result.staffing_issues
    generationStage.value = 'refreshing'
    failedStageIndex.value = 2
    generationSummary.value = `已生成 ${result.created} 节课，正在刷新周课表与日期课表`
    await loadTable()
    generationStage.value = 'done'
    failedStageIndex.value = 3
    generationSummary.value = result.staffing_issues.length
      ? `已完成 ${result.class_count} 个班、${result.created} 节课；仍有 ${result.staffing_issues.length} 个空堂受现有师资冲突限制`
      : `已完成 ${result.class_count} 个班、${result.created} 节课，当前师资条件下未发现可修复空堂`
    if (result.unplaced.length) ElMessage.warning(`已生成 ${result.created} 节，另有 ${result.unplaced.reduce((sum, item) => sum + item.count, 0)} 节未能排入`)
    else if (result.staffing_issues.length) ElMessage.warning(`课表已生成，但有 ${result.staffing_issues.length} 个时段需要增配师资或调整任教关系`)
    else ElMessage.success(`已为 ${result.class_count} 个班生成 ${result.created} 节课程`)
  } catch (error) {
    generationStage.value = 'error'
    generationSummary.value = error instanceof Error ? error.message : '生成课表失败'
    ElMessage.error(error instanceof Error ? error.message : '生成课表失败')
  } finally { generating.value = false }
}

async function saveAssignment() {
  if (!assignmentForm.teacher_id || !assignmentForm.subject_id || !assignmentForm.class_id) return ElMessage.warning('请选择教师、学科和班级')
  await schedulingApi.saveAssignment({ ...assignmentForm, teacher_id: assignmentForm.teacher_id, subject_id: assignmentForm.subject_id, class_id: assignmentForm.class_id, academic_year: academicYear.value, term: term.value })
  assignmentVisible.value = false
  await loadResources()
  ElMessage.success('任教关系已保存')
}

async function saveTeacher() {
  if (!teacherForm.name || !teacherForm.phone || !teacherForm.password) return ElMessage.warning('请填写完整教师信息')
  await schedulingApi.createTeacher(teacherForm)
  teacherVisible.value = false
  await loadResources()
  ElMessage.success('教师账号已创建')
}

function printPage() { window.print() }

watch([selectedClassId, academicYear, term, weekStart], loadTable)
onMounted(async () => { await loadResources(); await loadTable() })
</script>

<template>
  <main class="schedule-page" v-loading="loading">
    <header class="page-head">
      <div><span class="kicker">教务编排</span><h1>排课管理</h1><p>先维护任教关系，再生成周课表和具体日期表。</p></div>
      <div class="head-actions"><el-button @click="teacherVisible = true">新增教师</el-button><el-button @click="assignmentVisible = true">配置任教</el-button><el-button @click="conditionVisible = true">自定义条件</el-button><el-button type="primary" :loading="generating" :disabled="generating" @click="generateAll"><Icon v-if="!generating" name="calendar" :size="15" />{{ generating ? '正在生成' : '生成课表' }}</el-button></div>
    </header>

    <section v-if="generationStage !== 'idle'" class="generation-status" :class="{ blocked: generationStage === 'blocked', failed: generationStage === 'error' }" role="status" aria-live="polite">
      <div class="generation-copy">
        <div><strong>{{ generationStage === 'blocked' ? '条件需要调整' : generationStage === 'error' ? '生成未完成' : generationStage === 'done' ? '课表生成完成' : '正在生成课表' }}</strong><span>{{ generationSummary }}</span></div>
        <el-button v-if="!generating" link @click="generationStage = 'idle'">收起</el-button>
      </div>
      <div class="generation-track">
        <div v-for="(step, index) in generationSteps" :key="step.code" class="generation-step" :class="{ active: generationStepIndex === index && generating, done: generationStepIndex > index || generationStage === 'done', failed: (generationStage === 'blocked' || generationStage === 'error') && generationStepIndex === index }"><i aria-hidden="true" /><span>{{ step.label }}</span></div>
      </div>
      <ul v-if="validationIssues.length" class="validation-issues"><li v-for="issue in validationIssues" :key="`${issue.code}-${issue.entity_id}-${issue.related_id || 0}`">{{ issueText(issue) }}</li></ul>
      <div v-if="staffingIssues.length" class="staffing-warning">
        <strong>现有师资无法继续优化</strong>
        <ul><li v-for="issue in staffingIssues.slice(0, 8)" :key="`${issue.class_id}-${issue.weekday}-${issue.gap_period}`">{{ staffingIssueText(issue) }}</li></ul>
        <span v-if="staffingIssues.length > 8">另有 {{ staffingIssues.length - 8 }} 个冲突时段，请增配对应学科教师后重新排课。</span>
      </div>
    </section>

    <section class="control-bar">
      <label>学年<el-input v-model="academicYear" /></label>
      <label>学期<el-select v-model="term"><el-option label="第一学期" value="1" /><el-option label="第二学期" value="2" /></el-select></label>
      <label>查看班级<el-select v-model="selectedClassId" placeholder="选择班级"><el-option v-for="item in resources.classes" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
      <label v-if="activeTab === 'calendar'">所在周<el-date-picker v-model="weekStart" type="date" value-format="YYYY-MM-DD" format="YYYY年MM月DD日" /></label>
      <span class="control-note">{{ resources.assignments.filter(item => item.academic_year === academicYear && item.term === term).length }} 条任教关系 · {{ selectedStrategyNames }}</span>
    </section>

    <section class="work-surface">
      <div class="surface-head">
        <div><h2>{{ selectedClassName }}</h2><span>{{ academicYear }} 学年 · 第 {{ term }} 学期</span></div>
        <div class="view-switch"><button :class="{ active: activeTab === 'weekly' }" @click="activeTab = 'weekly'">周课表</button><button :class="{ active: activeTab === 'calendar' }" @click="activeTab = 'calendar'">日期课表</button><button @click="printPage"><Icon name="printer" :size="14" />打印</button></div>
      </div>
      <ScheduleGrid :entries="currentEntries" :date-mode="activeTab === 'calendar'" :week-start="weekStart" />
      <div v-if="!currentEntries.length" class="empty-hint">当前班级还没有课表，请先配置任教关系并生成。</div>
    </section>

    <section class="assignment-panel">
      <div class="panel-head"><div><h2>任教关系</h2><span>生成课表时以这里的每周课时为准</span></div><el-button link type="primary" @click="assignmentVisible = true">新增配置</el-button></div>
      <el-table :data="visibleAssignments" empty-text="当前班级暂无任教关系">
        <el-table-column prop="class_name" label="班级" min-width="150" /><el-table-column prop="subject_name" label="学科" width="110" /><el-table-column prop="teacher_name" label="教师" width="120" /><el-table-column prop="weekly_periods" label="每周课时" width="110" /><el-table-column prop="room" label="教室" min-width="120" />
      </el-table>
    </section>

    <el-dialog v-model="assignmentVisible" title="配置任教关系" width="500px">
      <el-form label-position="top">
        <div class="form-grid"><el-form-item label="班级"><el-select v-model="assignmentForm.class_id"><el-option v-for="item in resources.classes" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="学科"><el-select v-model="assignmentForm.subject_id"><el-option v-for="item in resources.subjects" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="教师"><el-select v-model="assignmentForm.teacher_id"><el-option v-for="item in resources.teachers" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item><el-form-item label="每周课时"><el-input-number v-model="assignmentForm.weekly_periods" :min="1" :max="20" /></el-form-item></div>
        <el-form-item label="固定教室（可选）"><el-input v-model="assignmentForm.room" placeholder="例如：高一教学楼 302" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="assignmentVisible = false">取消</el-button><el-button type="primary" @click="saveAssignment">保存配置</el-button></template>
    </el-dialog>

    <el-dialog v-model="teacherVisible" title="新增教师账号" width="440px">
      <el-form label-position="top"><el-form-item label="教师姓名"><el-input v-model="teacherForm.name" /></el-form-item><el-form-item label="手机号 / 登录账号"><el-input v-model="teacherForm.phone" /></el-form-item><el-form-item label="初始密码"><el-input v-model="teacherForm.password" type="password" show-password /></el-form-item></el-form>
      <template #footer><el-button @click="teacherVisible = false">取消</el-button><el-button type="primary" @click="saveTeacher">创建教师</el-button></template>
    </el-dialog>

    <el-dialog v-model="conditionVisible" title="自定义排课条件" width="560px">
      <el-form label-position="top">
        <div class="form-grid">
          <el-form-item label="班级每日最多课时"><el-input-number v-model="conditions.max_class_lessons_per_day" :min="1" :max="8" /></el-form-item>
          <el-form-item label="教师每日最多课时"><el-input-number v-model="conditions.max_teacher_lessons_per_day" :min="1" :max="8" /></el-form-item>
          <el-form-item label="同科每日最多课时"><el-input-number v-model="conditions.max_same_subject_per_day" :min="1" :max="3" /></el-form-item>
        </div>
        <el-form-item label="排课策略组合">
          <el-select v-model="conditions.strategy_codes" multiple placeholder="选择排课策略" class="strategy-select">
            <el-option v-for="option in strategyOptions" :key="option.code" :label="option.name" :value="option.code">
              <div class="strategy-option"><strong>{{ option.name }}</strong><span>{{ option.description }}</span></div>
            </el-option>
          </el-select>
          <span class="strategy-help">可组合多种策略；选择顺序代表优先级，系统按从左到右依次比较方案。</span>
        </el-form-item>
        <el-form-item label="全校禁排时段">
          <el-select v-model="conditions.forbidden_slots" multiple collapse-tags collapse-tags-tooltip clearable placeholder="例如：周五第 8 节不排课">
            <el-option v-for="slot in slotOptions" :key="slot.value" :label="slot.label" :value="slot.value" />
          </el-select>
        </el-form-item>
        <p class="condition-help">条件过紧时，系统会明确提示未排入课时，不会悄悄违反约束。</p>
      </el-form>
      <template #footer><el-button @click="conditions.forbidden_slots = []">清除禁排</el-button><el-button type="primary" @click="conditionVisible = false">应用条件</el-button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.schedule-page{max-width:1400px;margin:0 auto;padding:30px 34px 48px}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}.kicker{color:var(--blue-600);font-size:11px;font-weight:700}.page-head h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-head p{margin:0;color:var(--ink-500);font-size:13px}.head-actions{display:flex;gap:8px}.head-actions :deep(.el-button span){display:flex;align-items:center;gap:6px}.generation-status{margin:-8px 0 18px;padding:14px 16px;border:1px solid var(--line);border-left:3px solid var(--blue-600);background:var(--surface-0)}.generation-status.blocked,.generation-status.failed{border-left-color:var(--amber-500)}.generation-copy{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.generation-copy strong,.generation-copy span{display:block}.generation-copy strong{color:var(--ink-950);font-size:13px}.generation-copy span{margin-top:4px;color:var(--ink-500);font-size:11px}.generation-track{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin-top:14px}.generation-step{position:relative;display:flex;align-items:center;gap:7px;color:var(--ink-400);font-size:11px}.generation-step:after{content:'';position:absolute;right:8px;left:22px;top:6px;height:1px;background:var(--line)}.generation-step:last-child:after{display:none}.generation-step i{position:relative;z-index:1;width:12px;height:12px;border:2px solid var(--line);border-radius:50%;background:var(--surface-0)}.generation-step.active,.generation-step.done{color:var(--ink-950)}.generation-step.active i,.generation-step.done i{border-color:var(--blue-600);box-shadow:inset 0 0 0 2px var(--surface-0);background:var(--blue-600)}.generation-step.failed i{border-color:var(--amber-500);background:var(--amber-500)}.validation-issues{margin:13px 0 0;padding:10px 12px 0 28px;border-top:1px solid var(--line);color:var(--ink-700);font-size:11px;line-height:1.8}.control-bar{display:flex;align-items:flex-end;gap:16px;padding:16px 18px;border:1px solid var(--line);border-bottom:0;background:#fff}.control-bar label{display:flex;flex-direction:column;gap:7px;color:var(--ink-500);font-size:11px}.control-bar label:first-child{width:145px}.control-bar label:nth-child(2){width:130px}.control-bar label:nth-child(3){width:180px}.control-note{margin-left:auto;padding-bottom:9px;color:var(--ink-500);font-size:11px}.work-surface{padding:20px;border:1px solid var(--line);background:#fff}.surface-head,.panel-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.surface-head h2,.panel-head h2{margin:0;color:var(--ink-950);font-size:16px}.surface-head span,.panel-head span{display:block;margin-top:5px;color:var(--ink-500);font-size:11px}.view-switch{display:flex;border:1px solid var(--line)}.view-switch button{height:32px;padding:0 12px;border:0;border-right:1px solid var(--line);display:flex;align-items:center;gap:5px;background:#fff;color:var(--ink-500);font:inherit;font-size:11px;cursor:pointer}.view-switch button:last-child{border-right:0}.view-switch button.active{background:var(--graphite-950);color:#fff}.empty-hint{padding:18px;text-align:center;color:var(--ink-500);font-size:12px;border:1px solid var(--line);border-top:0}.assignment-panel{margin-top:16px;padding:20px;border:1px solid var(--line);background:#fff}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}.form-grid :deep(.el-select),.form-grid :deep(.el-input-number){width:100%}.strategy-select{width:100%}.strategy-option{display:flex;min-width:360px;align-items:center;justify-content:space-between;gap:20px}.strategy-option strong{color:var(--ink-950);font-size:12px}.strategy-option span,.strategy-help{color:var(--ink-500);font-size:10px}.strategy-help{display:block;margin-top:7px;line-height:1.5}.condition-help{margin:0;padding:12px;border-left:3px solid var(--blue-600);background:var(--surface-0);color:var(--ink-500);font-size:11px;line-height:1.6}@media(max-width:800px){.schedule-page{padding:22px 16px}.page-head{align-items:flex-start;flex-direction:column}.head-actions{flex-wrap:wrap}.generation-track{grid-template-columns:1fr;gap:8px}.generation-step:after{display:none}.control-bar{align-items:stretch;flex-direction:column}.control-bar label,.control-bar label:first-child,.control-bar label:nth-child(2),.control-bar label:nth-child(3){width:100%}.control-note{margin-left:0}.surface-head{align-items:flex-start;flex-direction:column;gap:12px}.form-grid{grid-template-columns:1fr}}@media print{.page-head,.generation-status,.control-bar,.assignment-panel,.view-switch{display:none}.schedule-page{padding:0}.work-surface{border:0;padding:0}}
.staffing-warning{margin-top:13px;padding:11px 12px;border-top:1px solid var(--line);background:rgba(245,158,11,.06);color:var(--ink-700);font-size:11px}.staffing-warning>strong{color:var(--ink-950);font-size:12px}.staffing-warning ul{margin:7px 0 4px;padding-left:18px;line-height:1.8}.staffing-warning>span{color:var(--ink-500)}
</style>
