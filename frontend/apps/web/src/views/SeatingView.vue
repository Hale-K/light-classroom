<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { orgApi, seatingApi } from '@zhiheng/api'
import type { ClassInfo, SeatArrangement, SeatEntry, Student } from '@zhiheng/shared'
import Icon from '@/components/Icon.vue'

const loading = ref(false)
const classes = ref<ClassInfo[]>([])
const arrangements = ref<SeatArrangement[]>([])
const students = ref<Student[]>([])
const selectedClassId = ref<number>()
const selectedArrangementId = ref<number>()
const form = reactive({ rows: 7, cols: 6, rule: 'roster', front_student_ids: [] as number[] })
const rules = [
  { value: 'roster', label: '按名册顺序', desc: '按学生名册序号从前到后排列' },
  { value: 'snake', label: '蛇形排列', desc: '相邻两行方向相反，便于连续点名' },
  { value: 'gender', label: '男女交错', desc: '在人数允许时尽量交替安排' },
  { value: 'random', label: '随机排座', desc: '使用固定种子生成可复现结果' },
]

const current = computed(() => arrangements.value.find((item) => item.id === selectedArrangementId.value) || arrangements.value[0])
const className = computed(() => classes.value.find((item) => item.id === selectedClassId.value)?.name || '请选择班级')
const capacity = computed(() => form.rows * form.cols)

function seatAt(row: number, col: number): SeatEntry | undefined {
  return current.value?.seats.find((seat) => seat.row === row && seat.col === col)
}

async function loadClasses() {
  classes.value = await orgApi.classes()
  selectedClassId.value ||= classes.value[0]?.id
}

async function loadArrangements() {
  if (!selectedClassId.value) return
  loading.value = true
  try {
    arrangements.value = await seatingApi.list(selectedClassId.value)
    selectedArrangementId.value = arrangements.value.find((item) => item.status === 'active')?.id || arrangements.value[0]?.id
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '座位表加载失败')
  } finally { loading.value = false }
}

async function loadStudents() {
  if (!selectedClassId.value) return
  students.value = await orgApi.students(selectedClassId.value)
  form.front_student_ids = form.front_student_ids.filter((id) => students.value.some((student) => student.id === id))
}

async function generate() {
  if (!selectedClassId.value) return ElMessage.warning('请先选择班级')
  loading.value = true
  try {
    const item = await seatingApi.generate({
      class_id: selectedClassId.value,
      rows: form.rows,
      cols: form.cols,
      rule: form.rule,
      seed: form.rule === 'random' ? Date.now() : undefined,
      front_student_ids: form.front_student_ids,
    })
    arrangements.value.unshift(item)
    selectedArrangementId.value = item.id
    ElMessage.success('新座位表已生成，确认后可启用')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '生成座位表失败')
  } finally { loading.value = false }
}

async function activate() {
  if (!current.value || current.value.status === 'active') return
  await ElMessageBox.confirm('启用后，当前正在使用的座位表会自动归档。', '启用座位表', { type: 'warning', confirmButtonText: '确认启用' })
  await seatingApi.activate(current.value.id)
  await loadArrangements()
  ElMessage.success('座位表已启用')
}

watch(selectedClassId, async () => { await Promise.all([loadArrangements(), loadStudents()]) })
onMounted(async () => { await loadClasses(); await Promise.all([loadArrangements(), loadStudents()]) })
</script>

<template>
  <main class="seating-page" v-loading="loading">
    <header class="page-head">
      <div><span class="kicker">班级管理</span><h1>班级排座</h1><p>按班级名册生成座位方案，确认后启用并保留历史版本。</p></div>
      <div class="head-actions"><el-button :disabled="!current || current.status === 'active'" @click="activate">启用当前方案</el-button><el-button type="primary" @click="generate"><Icon name="grid" :size="15" />生成座位表</el-button></div>
    </header>

    <div class="layout-grid">
      <aside class="config-panel">
        <div class="panel-title"><h2>排座条件</h2><span>选择班级和教室布局</span></div>
        <label>班级<el-select v-model="selectedClassId" placeholder="选择班级"><el-option v-for="item in classes" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
        <div class="size-row"><label>行数<el-input-number v-model="form.rows" :min="1" :max="20" /></label><label>列数<el-input-number v-model="form.cols" :min="1" :max="20" /></label></div>
        <div class="capacity"><span>教室容量</span><strong>{{ capacity }}</strong><small>个座位</small></div>
        <label class="priority-field">自定义前排学生<el-select v-model="form.front_student_ids" multiple collapse-tags collapse-tags-tooltip clearable :max-collapse-tags="2" placeholder="最多选择 20 人"><el-option v-for="student in students" :key="student.id" :label="student.name" :value="student.id" :disabled="form.front_student_ids.length >= 20 && !form.front_student_ids.includes(student.id)" /></el-select></label>
        <div class="rule-list"><span class="field-label">排列规则</span><button v-for="rule in rules" :key="rule.value" type="button" :class="{ active: form.rule === rule.value }" @click="form.rule = rule.value"><i /><span><strong>{{ rule.label }}</strong><small>{{ rule.desc }}</small></span></button></div>
        <div class="history"><div class="history-head"><span>历史方案</span><b>{{ arrangements.length }}</b></div><button v-for="item in arrangements" :key="item.id" type="button" :class="{ active: current?.id === item.id }" @click="selectedArrangementId = item.id"><span>{{ item.rows }} 行 × {{ item.cols }} 列</span><small>{{ item.status === 'active' ? '使用中' : item.status === 'archived' ? '已归档' : '草稿' }}</small></button></div>
      </aside>

      <section class="seat-surface">
        <div class="surface-head"><div><h2>{{ className }}座位表</h2><span v-if="current">{{ rules.find(rule => rule.value === current?.rule)?.label }} · {{ current.seats.length }} 名学生</span><span v-else>尚未生成座位方案</span></div><el-tag v-if="current" :type="current.status === 'active' ? 'success' : 'info'">{{ current.status === 'active' ? '正在使用' : current.status === 'archived' ? '已归档' : '待确认' }}</el-tag></div>
        <div class="podium"><span>讲台</span></div>
        <div v-if="current" class="seat-grid" :style="{ gridTemplateColumns: `repeat(${current.cols}, minmax(92px, 1fr))` }">
          <div v-for="row in current.rows" :key="row" class="seat-row-group">
            <div v-for="col in current.cols" :key="`${row}-${col}`" class="seat" :class="{ empty: !seatAt(row, col) }">
              <template v-if="seatAt(row, col)"><span class="seat-no">{{ row }}-{{ col }}</span><strong>{{ seatAt(row, col)?.student_name }}</strong><small>{{ seatAt(row, col)?.student_no || '未录学号' }}</small></template>
              <span v-else class="empty-text">空位</span>
            </div>
          </div>
        </div>
        <div v-else class="empty-state"><Icon name="grid" :size="30" /><strong>还没有座位表</strong><span>设置左侧条件后点击“生成座位表”。</span></div>
        <div class="door">前门</div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.seating-page{max-width:1400px;margin:0 auto;padding:30px 34px 48px}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:24px}.kicker{color:var(--blue-600);font-size:11px;font-weight:700}.page-head h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-head p{margin:0;color:var(--ink-500);font-size:13px}.head-actions{display:flex;gap:8px}.head-actions :deep(.el-button span){display:flex;align-items:center;gap:6px}.layout-grid{display:grid;grid-template-columns:286px 1fr;border:1px solid var(--line);background:#fff}.config-panel{padding:20px;border-right:1px solid var(--line)}.panel-title{margin-bottom:20px}.panel-title h2,.surface-head h2{margin:0;color:var(--ink-950);font-size:16px}.panel-title span,.surface-head span{display:block;margin-top:5px;color:var(--ink-500);font-size:11px}.config-panel>label,.size-row label{display:flex;flex-direction:column;gap:7px;margin-bottom:16px;color:var(--ink-500);font-size:11px}.config-panel :deep(.el-select),.size-row :deep(.el-input-number){width:100%}.size-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.capacity{display:flex;align-items:baseline;padding:12px 0 17px;border-bottom:1px solid var(--line);color:var(--ink-500);font-size:11px}.capacity strong{margin-left:auto;color:var(--ink-950);font-size:24px}.capacity small{margin-left:4px}.field-label{display:block;margin:17px 0 8px;color:var(--ink-500);font-size:11px}.rule-list button{width:100%;display:flex;align-items:flex-start;gap:10px;padding:10px 8px;border:1px solid transparent;background:#fff;text-align:left;cursor:pointer}.rule-list button:hover{background:var(--surface-0)}.rule-list button.active{border-color:var(--blue-600);background:var(--blue-100)}.rule-list button i{width:8px;height:8px;margin-top:4px;border:1px solid #aab3c0;border-radius:50%}.rule-list button.active i{border:2px solid #fff;background:var(--blue-600);box-shadow:0 0 0 1px var(--blue-600)}.rule-list button span{display:flex;flex-direction:column}.rule-list strong{color:var(--ink-950);font-size:12px}.rule-list small{margin-top:4px;color:var(--ink-500);font-size:10px;line-height:1.5}.history{margin-top:20px;padding-top:16px;border-top:1px solid var(--line)}.history-head{display:flex;justify-content:space-between;margin-bottom:8px;color:var(--ink-500);font-size:11px}.history button{width:100%;display:flex;justify-content:space-between;padding:8px;border:0;background:#fff;color:var(--ink-700);font:inherit;font-size:11px;cursor:pointer}.history button.active{background:var(--surface-0);color:var(--blue-600)}.history button small{color:var(--ink-500)}.seat-surface{min-width:0;padding:20px 26px 30px;background:#f8f9fb}.surface-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}.podium{width:42%;height:34px;margin:0 auto 28px;display:grid;place-items:center;border:1px solid #cfd6df;border-top:3px solid var(--graphite-950);background:#fff;color:var(--ink-700);font-size:11px}.seat-grid{display:grid;gap:12px;overflow:auto}.seat-row-group{display:contents}.seat{min-height:68px;padding:9px;border:1px solid #cfd8e5;border-left:3px solid var(--blue-600);display:flex;flex-direction:column;justify-content:center;background:#fff}.seat-no{color:var(--ink-500);font-size:9px}.seat strong{margin-top:3px;color:var(--ink-950);font-size:12px}.seat small{margin-top:3px;color:var(--ink-500);font-size:9px}.seat.empty{align-items:center;border-left:1px dashed #d9dee6;border-style:dashed;background:transparent}.empty-text{color:#b8c0cb;font-size:10px}.empty-state{min-height:420px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--ink-500)}.empty-state svg{color:#aab3c0}.empty-state strong{margin-top:12px;color:var(--ink-950);font-size:14px}.empty-state span{margin-top:6px;font-size:11px}.door{margin-top:24px;padding-top:10px;border-top:1px solid var(--line);color:var(--ink-500);font-size:10px;text-align:right}@media(max-width:960px){.seating-page{padding:22px 16px}.page-head{align-items:flex-start;flex-direction:column}.layout-grid{grid-template-columns:1fr}.config-panel{border-right:0;border-bottom:1px solid var(--line)}}
</style>
