<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import Icon from '@/components/Icon.vue'
import EmptyState from '@/components/EmptyState.vue'
import { examApi, orgApi, scanApi, gradingApi } from '@zhiheng/api'
import { EXAM_STATUS_LABEL, EXAM_TYPE_LABEL, type Exam, type Paper, type ScanBatch } from '@zhiheng/shared'

const router = useRouter()
const loading = ref(true)
const exams = ref<Exam[]>([])
const batches = ref<ScanBatch[]>([])
const studentTotal = ref(0)
const chartEl = ref<HTMLElement>()

interface PaperProgress { paperId: number; title: string; graded: number; total: number }
const progress = ref<PaperProgress[]>([])
const stat = computed(() => ({
  ongoing: exams.value.filter((e) => e.status === 'ongoing').length,
  pendingBatches: batches.value.filter((b) => b.status && b.status !== 'confirmed').length,
  finalizedPapers: progress.value.length,
  students: studentTotal.value,
}))
const totalGraded = computed(() => progress.value.reduce((s, p) => s + p.graded, 0))
const totalSubs = computed(() => progress.value.reduce((s, p) => s + p.total, 0))
const overallRate = computed(() => totalSubs.value ? Math.round((totalGraded.value / totalSubs.value) * 100) : 0)
const todayLabel = computed(() => new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date()))
const nextAction = computed(() => {
  const assigned = batches.value.find((b) => b.status === 'assigned')
  if (assigned) return { label: '继续批改', sub: '有一批答卷正在等你', path: `/grading/${assigned.paper_id}` }
  const uploaded = batches.value.find((b) => b.status === 'uploaded' || b.status === 'split')
  if (uploaded) return { label: '处理扫描批次', sub: '还有扫描件需要确认', path: '/scans' }
  return { label: '查看考试安排', sub: '从最近的考试开始', path: '/exams' }
})

async function loadData() {
  loading.value = true
  try {
    const [examList, batchList, sc] = await Promise.all([examApi.list(), scanApi.batches(), orgApi.studentCount()])
    exams.value = examList
    batches.value = batchList
    studentTotal.value = sc.total
    const paperProgress: PaperProgress[] = []
    for (const exam of examList.slice(0, 5)) {
      const detail = await examApi.detail(exam.id)
      const finalized = (detail.papers || []).filter((p) => p.status === 'finalized')
      const result = await Promise.allSettled(finalized.map((p) => gradingApi.queue(p.id)))
      finalized.forEach((p: Paper, i) => {
        const queue = result[i].status === 'fulfilled' ? result[i].value : []
        paperProgress.push({ paperId: p.id, title: p.title, graded: queue.filter((s) => s.status === 'graded').length, total: queue.length })
      })
    }
    progress.value = paperProgress
    renderChart()
  } finally { loading.value = false }
}

function getCssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function renderChart() {
  if (!chartEl.value) return
  const chart = echarts.getInstanceByDom(chartEl.value) || echarts.init(chartEl.value)
  const primary = getCssVar('--primary') || '#2563EB'
  const line = getCssVar('--line') || '#E2E8F0'
  const ink950 = getCssVar('--ink-950') || '#0F172A'
  chart.setOption({
    color: [primary, line],
    tooltip: { trigger: 'item' },
    series: [{ type: 'pie', radius: ['70%', '85%'], center: ['50%', '45%'], silent: true, label: { show: true, position: 'center', formatter: () => `${overallRate.value}%`, color: ink950, fontSize: 24, fontWeight: 700 }, labelLine: { show: false }, data: totalSubs.value ? [{ value: totalGraded.value, name: '已批阅' }, { value: totalSubs.value - totalGraded.value, name: '待批阅' }] : [{ value: 1, name: '暂无数据' }] }],
  })
}

function onThemeChange() {
  renderChart()
}

const statusTag = (s?: string) => ({ preparing: 'info', ongoing: 'primary', ended: 'success', archived: 'warning' } as const)[s as string] || 'info'
const batchStatusLabel = (s?: string) => ({ uploaded: '已上传', split: '已切分', assigned: '已分配', confirmed: '已确认' })[s as string] || s || '未知'
const batchStatusTag = (s?: string) => ({ uploaded: 'warning', split: 'primary', assigned: 'success', confirmed: 'info' })[s as string] || 'info'
function openGrading(paperId: number) { router.push(`/grading/${paperId}`) }
onMounted(() => {
  loadData()
  window.addEventListener('theme-change', onThemeChange)
})
onBeforeUnmount(() => {
  window.removeEventListener('theme-change', onThemeChange)
})
</script>

<template>
  <div class="dashboard-page" v-loading="loading">
    <div class="dash-topline">
      <div>
        <div class="eyebrow">{{ todayLabel }}</div>
        <h1>早上好，老师</h1>
        <p>这里汇总今天需要处理的考试、扫描和阅卷任务。</p>
      </div>
      <div class="dash-actions">
        <button class="btn-secondary" type="button" @click="router.push('/exams')"><Icon name="calendar" :size="15" />考试安排</button>
        <button class="btn-primary" type="button" @click="router.push('/scans')"><Icon name="upload" :size="15" />上传扫描件</button>
      </div>
    </div>

    <section class="focus-grid">
      <div class="focus-panel">
        <div class="focus-copy">
          <span class="focus-label">优先处理</span>
          <h2>{{ nextAction.label }}</h2>
          <p>{{ nextAction.sub }}，完成后相关进度会同步更新。</p>
          <button type="button" class="focus-button" @click="router.push(nextAction.path)">{{ nextAction.label }}<Icon name="arrow-right" :size="15" /></button>
        </div>
        <div class="focus-ring">
          <div ref="chartEl" class="ring-chart" />
          <span>批改完成率</span>
        </div>
        <div class="focus-foot">
          <span>阅卷队列</span>
          <strong>{{ totalGraded }} <em>/ {{ totalSubs }}</em></strong>
        </div>
      </div>

      <div class="signal-panel">
        <div class="panel-title">当前概况</div>
        <div class="signal-list">
          <div class="signal-row">
            <span class="signal-icon"><Icon name="scan" :size="17" /></span>
            <div>
              <b>{{ stat.pendingBatches }} 个</b>
              <small>待处理扫描批次</small>
            </div>
            <Icon name="chevron-right" :size="14" class="row-arrow" />
          </div>
          <div class="signal-row">
            <span class="signal-icon"><Icon name="calendar" :size="17" /></span>
            <div>
              <b>{{ stat.ongoing }} 场</b>
              <small>正在进行的考试</small>
            </div>
            <Icon name="chevron-right" :size="14" class="row-arrow" />
          </div>
          <div class="signal-row">
            <span class="signal-icon"><Icon name="users" :size="17" /></span>
            <div>
              <b>{{ stat.students }} 人</b>
              <small>当前学生名册</small>
            </div>
            <Icon name="chevron-right" :size="14" class="row-arrow" />
          </div>
        </div>
      </div>
    </section>

    <div class="metric-strip">
      <div class="metric-item">
        <span>正在进行</span>
        <strong>{{ stat.ongoing }}</strong>
        <small>场考试</small>
      </div>
      <div class="metric-item">
        <span>已定稿试卷</span>
        <strong>{{ stat.finalizedPapers }}</strong>
        <small>份</small>
      </div>
      <div class="metric-item">
        <span>已批阅答卷</span>
        <strong>{{ totalGraded }}</strong>
        <small>份</small>
      </div>
      <div class="metric-item">
        <span>学生名册</span>
        <strong>{{ stat.students }}</strong>
        <small>人</small>
      </div>
    </div>

    <div class="content-grid">
      <section class="surface-card">
        <div class="section-head">
          <h3>最近考试</h3>
          <button type="button" class="text-link" @click="router.push('/exams')">查看全部<Icon name="arrow-right" :size="13" /></button>
        </div>
        <EmptyState v-if="!exams.length" icon="calendar" title="暂无考试" desc="创建一场考试，开始轻量建卷" action-text="去建考试" :height="240" @action="router.push('/exams')" />
        <div v-else class="exam-list">
          <button v-for="(exam, index) in exams.slice(0, 5)" :key="exam.id" type="button" class="exam-row" @click="router.push('/exams')">
            <span class="exam-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="exam-date">{{ (exam.created_at || '').slice(5, 10) || '--/--' }}</span>
            <span class="exam-title">{{ exam.name }}</span>
            <span class="exam-type">{{ EXAM_TYPE_LABEL[exam.exam_type || ''] || '月考' }}</span>
            <el-tag size="small" :type="statusTag(exam.status)">{{ EXAM_STATUS_LABEL[exam.status] || exam.status }}</el-tag>
            <Icon name="chevron-right" :size="14" class="row-arrow" />
          </button>
        </div>
      </section>

      <section class="surface-card">
        <div class="section-head">
          <h3>阅卷队列</h3>
          <span class="queue-total">{{ totalGraded }}/{{ totalSubs }}</span>
        </div>
        <div v-if="!progress.length" class="queue-empty">
          <Icon name="keyboard" :size="22" />
          <span>扫描分配后，队列会出现在这里。</span>
        </div>
        <div v-else class="queue-list">
          <button v-for="p in progress.slice(0, 4)" :key="p.paperId" type="button" class="queue-row" @click="openGrading(p.paperId)">
            <span class="queue-name">{{ p.title }}</span>
            <span class="queue-bar"><i :style="{ width: p.total ? `${p.graded / p.total * 100}%` : '0%' }" /></span>
            <strong>{{ p.total ? Math.round(p.graded / p.total * 100) : 0 }}%</strong>
          </button>
        </div>
        <button v-if="progress.length" type="button" class="queue-footer" @click="openGrading(progress[0].paperId)">
          进入批改工作台<Icon name="arrow-right" :size="13" />
        </button>
      </section>
    </div>

    <section class="surface-card scan-card">
      <div class="section-head">
        <h3>扫描进卷</h3>
        <button type="button" class="text-link" @click="router.push('/scans')">进入进卷中心<Icon name="arrow-right" :size="13" /></button>
      </div>
      <div v-if="!batches.length" class="scan-empty">
        <span class="scan-empty-mark"><Icon name="scan" :size="20" /></span>
        <div>
          <strong>还没有扫描批次</strong>
          <small>试卷定稿后，上传扫描件即可开始分配。</small>
        </div>
        <button type="button" class="btn-secondary btn-sm" @click="router.push('/scans')">去上传</button>
      </div>
      <div v-else class="scan-table">
        <div class="scan-head">
          <span>批次</span><span>页数</span><span>状态</span><span>创建时间</span><span>操作</span>
        </div>
        <div v-for="row in batches.slice(0, 4)" :key="row.id" class="scan-row">
          <span class="scan-name"><Icon name="qrcode" :size="15" />{{ row.file_name || `扫描批次 #${row.id}` }}</span>
          <span class="num">{{ row.page_count ?? 0 }}</span>
          <span><el-tag size="small" :type="batchStatusTag(row.status)">{{ batchStatusLabel(row.status) }}</el-tag></span>
          <span class="muted">{{ (row.created_at || '').slice(0, 10) }}</span>
          <button type="button" class="text-link" @click="row.status === 'assigned' ? openGrading(row.paper_id) : router.push('/scans')">{{ row.status === 'assigned' ? '去打分' : '处理' }}</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dashboard-page {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px 32px 40px;
}

/* 顶部问候 */
.dash-topline {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 24px;
}
.eyebrow {
  color: var(--ink-400);
  font-size: 12px;
  font-weight: 500;
}
h1 {
  margin: 6px 0 0;
  color: var(--ink-950);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.dash-topline p {
  margin: 6px 0 0;
  color: var(--ink-500);
  font-size: 13px;
}
.dash-actions {
  display: flex;
  gap: 8px;
}

/* 按钮 */
.btn-primary,
.btn-secondary {
  height: 36px;
  border-radius: var(--radius-control);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 14px;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.15s;
}
.btn-primary {
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
}
.btn-primary:hover {
  background: var(--primary-hover);
  border-color: var(--primary-hover);
}
.btn-secondary {
  border: 1px solid var(--line);
  background: var(--surface-1);
  color: var(--ink-700);
}
.btn-secondary:hover {
  border-color: var(--ink-400);
  color: var(--ink-950);
}
.btn-sm {
  height: 30px;
  padding: 0 10px;
  font-size: 11px;
}

/* 优先处理 + 概况 */
.focus-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.focus-panel {
  padding: 24px;
  display: grid;
  grid-template-columns: 1fr 150px;
  grid-template-rows: 1fr auto;
  border-radius: var(--radius-card);
  background: var(--surface-1);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-sm);
  gap: 0 20px;
}
.focus-label {
  color: var(--ink-400);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.focus-copy h2 {
  margin: 12px 0 6px;
  font-size: 22px;
  color: var(--ink-950);
  font-weight: 700;
  letter-spacing: -0.3px;
}
.focus-copy p {
  max-width: 320px;
  margin: 0;
  color: var(--ink-500);
  font-size: 12px;
  line-height: 1.6;
}
.focus-button {
  margin-top: 18px;
  border: 0;
  border-radius: var(--radius-control);
  padding: 8px 14px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #fff;
  background: var(--primary);
  font: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.focus-button:hover {
  background: var(--primary-hover);
}
.focus-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--ink-400);
  font-size: 11px;
}
.ring-chart {
  width: 130px;
  height: 130px;
}
.focus-ring > span {
  margin-top: -16px;
}
.focus-foot {
  grid-column: 1 / -1;
  align-self: end;
  padding-top: 14px;
  margin-top: 14px;
  border-top: 1px solid var(--line);
  color: var(--ink-400);
  font-size: 11px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.focus-foot strong {
  color: var(--ink-950);
  font-size: 14px;
  font-weight: 600;
}
.focus-foot em {
  font-style: normal;
  color: var(--ink-400);
  font-weight: 400;
}

/* 概况面板 */
.signal-panel {
  padding: 20px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-1);
  box-shadow: var(--shadow-sm);
}
.panel-title {
  color: var(--ink-950);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}
.signal-list {
  margin-top: 8px;
}
.signal-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 0;
  border-bottom: 1px solid var(--line-light);
  cursor: pointer;
}
.signal-row:last-child {
  border-bottom: 0;
}
.signal-row:hover .row-arrow {
  color: var(--ink-500);
}
.signal-icon {
  width: 32px;
  height: 32px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  background: var(--surface-2);
  color: var(--ink-500);
}
.signal-row div {
  flex: 1;
  min-width: 0;
}
.signal-row b {
  display: block;
  color: var(--ink-950);
  font-size: 13px;
  font-weight: 600;
}
.signal-row small {
  display: block;
  margin-top: 2px;
  color: var(--ink-400);
  font-size: 11px;
}
.row-arrow {
  color: var(--ink-400);
  flex-shrink: 0;
  transition: color 0.15s;
}

/* 指标条 */
.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  margin-bottom: 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-1);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.metric-item {
  padding: 16px 20px;
  border-right: 1px solid var(--line);
}
.metric-item:last-child {
  border-right: 0;
}
.metric-item span {
  color: var(--ink-400);
  font-size: 11px;
  font-weight: 500;
}
.metric-item strong {
  display: block;
  margin-top: 6px;
  color: var(--ink-950);
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
}
.metric-item small {
  color: var(--ink-400);
  font-size: 11px;
  margin-left: 4px;
}

/* 内容网格 */
.content-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.surface-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--surface-1);
  padding: 20px;
  box-shadow: var(--shadow-sm);
}
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.section-head h3 {
  margin: 0;
  color: var(--ink-950);
  font-size: 14px;
  font-weight: 600;
}
.text-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: var(--blue-600);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  padding: 0;
  transition: color 0.15s;
}
.text-link:hover {
  color: var(--navy-700);
}

/* 考试列表 */
.exam-list {
  display: flex;
  flex-direction: column;
}
.exam-row {
  display: grid;
  grid-template-columns: 28px 54px 1fr 56px 72px 16px;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 0 4px;
  border: 0;
  border-top: 1px solid var(--line-light);
  background: transparent;
  text-align: left;
  cursor: pointer;
  font: inherit;
  transition: background 0.15s;
}
.exam-row:hover {
  background: var(--surface-0);
}
.exam-row:hover .row-arrow {
  color: var(--ink-500);
}
.exam-index,
.exam-date,
.exam-type,
.muted {
  color: var(--ink-400);
  font-size: 12px;
}
.exam-index {
  color: var(--ink-500);
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.exam-title {
  color: var(--ink-950);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 阅卷队列 */
.queue-total {
  color: var(--ink-950);
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.queue-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin: 4px 0 16px;
}
.queue-row {
  display: grid;
  grid-template-columns: 1fr 80px 34px;
  align-items: center;
  gap: 10px;
  border: 0;
  padding: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.queue-name {
  color: var(--ink-700);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.queue-bar {
  height: 5px;
  border-radius: 3px;
  background: var(--surface-2);
  overflow: hidden;
}
.queue-bar i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--blue-600);
  transition: width 0.3s;
}
.queue-row strong {
  color: var(--ink-950);
  font-size: 12px;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.queue-footer {
  width: 100%;
  padding: 12px 0 0;
  border: 0;
  border-top: 1px solid var(--line-light);
  background: transparent;
  color: var(--blue-600);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.queue-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 140px;
  color: var(--ink-400);
  font-size: 12px;
}
.queue-empty svg {
  color: var(--ink-400);
}

/* 扫描批次 */
.scan-card {
  padding-bottom: 12px;
}
.scan-card .section-head {
  margin-bottom: 8px;
}
.scan-table {
  width: 100%;
}
.scan-head,
.scan-row {
  display: grid;
  grid-template-columns: 1.7fr 0.5fr 0.7fr 0.8fr 0.7fr;
  align-items: center;
  gap: 12px;
}
.scan-head {
  padding: 8px;
  color: var(--ink-400);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.scan-row {
  min-height: 44px;
  padding: 0 8px;
  border-top: 1px solid var(--line-light);
  font-size: 12px;
}
.scan-name {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ink-950);
  font-weight: 500;
}
.scan-name svg {
  color: var(--ink-400);
}
.scan-empty {
  min-height: 80px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 8px;
  border-top: 1px solid var(--line-light);
}
.scan-empty-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--ink-500);
  background: var(--surface-2);
  flex-shrink: 0;
}
.scan-empty div {
  flex: 1;
}
.scan-empty strong,
.scan-empty small {
  display: block;
}
.scan-empty strong {
  color: var(--ink-950);
  font-size: 13px;
  font-weight: 600;
}
.scan-empty small {
  margin-top: 3px;
  color: var(--ink-400);
  font-size: 11px;
}

@media (max-width: 1100px) {
  .dashboard-page {
    padding: 24px;
  }
  .focus-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 760px) {
  .dashboard-page {
    padding: 20px 16px;
  }
  .dash-topline {
    align-items: flex-start;
    flex-direction: column;
    gap: 14px;
  }
  .metric-strip {
    grid-template-columns: repeat(2, 1fr);
  }
  .metric-item:nth-child(2) {
    border-right: 0;
  }
  .metric-item:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }
  .scan-head {
    display: none;
  }
  .scan-row {
    grid-template-columns: 1.4fr 0.5fr 0.8fr;
  }
  .scan-row > :nth-child(4),
  .scan-row > :nth-child(5) {
    display: none;
  }
}
</style>
