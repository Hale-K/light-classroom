<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi, gaokaoApi, type GaokaoOverview } from '@zhiheng/api'

type GaokaoMode = '3+1+2' | '3+3' | 'traditional'
const academicYear = ref('2026-2027')
const term = ref('1')
const gradeId = ref<number>()
const mode = ref<GaokaoMode>('3+1+2')
const overview = ref<GaokaoOverview>()
const loading = ref(false)
const generating = ref('')

const isWalkClass = computed(() => mode.value !== 'traditional')
const modeTitle = computed(() => ({
  '3+1+2': '3+1+2 选科与走班',
  '3+3': '3+3 选科与走班',
  traditional: '传统文理分科',
}[mode.value]))

async function load() {
  loading.value = true
  try {
    const data = await gaokaoApi.overview({
      academic_year: academicYear.value, term: term.value, grade_id: gradeId.value,
    })
    overview.value = data
    gradeId.value ||= data.grades[0]?.id
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '选科数据加载失败')
  } finally {
    loading.value = false
  }
}

async function generateClasses() {
  if (!gradeId.value) return ElMessage.warning('请选择年级')
  generating.value = 'classes'
  try {
    const result = await gaokaoApi.generateTeachingClasses({
      grade_id: gradeId.value, academic_year: academicYear.value, term: term.value, capacity: 40,
    })
    ElMessage.success(`已生成 ${result.created} 个教学班`)
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '教学班生成失败')
  } finally {
    generating.value = ''
  }
}

async function generateSchedule() {
  if (!gradeId.value) return ElMessage.warning('请选择年级')
  generating.value = 'schedule'
  try {
    const result = await gaokaoApi.generateSchedule({
      grade_id: gradeId.value, academic_year: academicYear.value, term: term.value,
    })
    ElMessage.success(`已生成 ${result.created} 个走班课时`)
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '走班课表生成失败')
  } finally {
    generating.value = ''
  }
}

onMounted(async () => {
  const menu = await authApi.menus()
  mode.value = menu.gaokao_mode || '3+1+2'
  await load()
})
</script>

<template>
  <section class="gaokao-page" v-loading="loading">
    <header class="page-header">
      <div><span class="eyebrow">GAOKAO POLICY</span><h1>{{ modeTitle }}</h1><p>学校默认模式决定功能入口，届别方案可独立覆盖。</p></div>
      <div v-if="isWalkClass" class="actions">
        <el-button :loading="generating === 'classes'" @click="generateClasses">生成教学班</el-button>
        <el-button type="primary" :loading="generating === 'schedule'" @click="generateSchedule">生成走班课表</el-button>
      </div>
    </header>

    <div class="filters">
      <el-input v-model="academicYear" style="width: 150px" @change="load" />
      <el-select v-model="term" style="width: 100px" @change="load"><el-option label="上学期" value="1" /><el-option label="下学期" value="2" /></el-select>
      <el-select v-model="gradeId" placeholder="选择年级" style="width: 140px" @change="load"><el-option v-for="grade in overview?.grades" :key="grade.id" :label="grade.name" :value="grade.id" /></el-select>
      <span class="policy-chip">{{ overview?.scheme?.name || '尚未建立届别方案' }}</span>
    </div>

    <div class="metrics">
      <div><span>年级学生</span><strong>{{ overview?.stats.student_count || 0 }}</strong></div>
      <div><span>{{ isWalkClass ? '已确认选科' : '已确认分科' }}</span><strong>{{ overview?.stats.confirmed_count || 0 }}</strong></div>
      <div><span>确认覆盖率</span><strong>{{ overview?.stats.coverage_rate || 0 }}%</strong></div>
      <div><span>{{ isWalkClass ? '教学班' : '科类' }}</span><strong>{{ isWalkClass ? overview?.stats.teaching_class_count || 0 : overview?.stats.combination_count || 0 }}</strong></div>
    </div>

    <div class="content-grid">
      <el-card shadow="never"><template #header><strong>{{ isWalkClass ? '选科组合分布' : '文理分科分布' }}</strong></template><el-table :data="overview?.combinations || []" height="360"><el-table-column prop="label" label="组合" /><el-table-column prop="count" label="人数" width="100" /></el-table></el-card>
      <el-card v-if="isWalkClass" shadow="never"><template #header><strong>学科资源需求</strong></template><el-table :data="overview?.subject_demand || []" height="360"><el-table-column prop="subject_name" label="学科" /><el-table-column prop="student_count" label="学生" width="80" /><el-table-column prop="recommended_class_count" label="建议班数" width="100" /><el-table-column prop="teacher_count" label="教师" width="80" /></el-table></el-card>
      <el-card v-else shadow="never" class="policy-note"><h3>行政班教学</h3><p>传统文理模式保留行政班排课，不开放走班教学班和走班课表功能。</p></el-card>
    </div>
  </section>
</template>

<style scoped>
.gaokao-page{min-height:100%;padding:32px 38px;background:var(--surface-0)}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.eyebrow{font-size:11px;color:var(--ink-400);letter-spacing:.8px}h1{margin:7px 0 6px;font-size:28px;color:var(--ink-950)}.page-header p{margin:0;color:var(--ink-500);font-size:13px}.actions,.filters{display:flex;align-items:center;gap:10px}.filters{margin:24px 0 16px;padding:14px;border:1px solid var(--line);border-radius:10px;background:#fff}.policy-chip{margin-left:auto;padding:6px 10px;border-radius:6px;background:var(--surface-1);color:var(--ink-600);font-size:12px}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.metrics>div{padding:17px 18px;border:1px solid var(--line);border-radius:9px;background:#fff}.metrics span{display:block;color:var(--ink-500);font-size:12px}.metrics strong{display:block;margin-top:9px;color:var(--ink-950);font-size:25px}.content-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:16px}.policy-note p{color:var(--ink-500);line-height:1.7}@media(max-width:900px){.gaokao-page{padding:24px 18px}.page-header{align-items:flex-start;flex-direction:column}.metrics,.content-grid{grid-template-columns:1fr 1fr}.filters{flex-wrap:wrap}.policy-chip{margin-left:0}}@media(max-width:600px){.metrics,.content-grid{grid-template-columns:1fr}}
</style>
