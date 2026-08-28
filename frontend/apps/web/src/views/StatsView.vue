<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import { statsApi } from '@zhiheng/api'
import type { PaperSummary } from '@zhiheng/shared'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const paperId = Number(route.params.paperId)
const loading = ref(true)
const summary = ref<PaperSummary | null>(null)
const byClass = ref<Array<Record<string, unknown>>>([])
const byQuestion = ref<Array<Record<string, unknown>>>([])

function cssVar(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function chartColors() {
  return {
    primary: cssVar('--primary', '#1D4ED8'),
    cyan: cssVar('--cyan-500', '#0891B2'),
    amber: cssVar('--amber-500', '#B45309'),
    line: cssVar('--line', '#E2E8F0'),
    lineLight: cssVar('--line-light', '#F1F5F9'),
    ink500: cssVar('--ink-500', '#64748B'),
    ink700: cssVar('--ink-700', '#334155'),
  }
}

function ensureChart(el: HTMLElement) {
  return echarts.getInstanceByDom(el) || echarts.init(el)
}

function renderDist(el: HTMLElement) {
  const c = chartColors()
  const dist = summary.value?.distribution || []
  ensureChart(el).setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 30, right: 12, top: 16, bottom: 26 },
    xAxis: { type: 'category', data: dist.map((d) => `${d.label}分`), axisLine: { lineStyle: { color: c.line } }, axisLabel: { color: c.ink500 } },
    yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: c.lineLight } } },
    series: [{ type: 'bar', data: dist.map((d) => d.count), barWidth: 34, itemStyle: { color: c.primary, borderRadius: [6, 6, 0, 0] } }],
  })
}

function renderClass(el: HTMLElement) {
  const c = chartColors()
  ensureChart(el).setOption({
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, icon: 'circle', itemWidth: 10, textStyle: { color: c.ink500 } },
    grid: { left: 36, right: 12, top: 20, bottom: 60 },
    xAxis: { type: 'category', data: byClass.value.map((c2) => c2.class_name || '未分班'), axisLabel: { color: c.ink500 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: c.lineLight } } },
    series: [
      { name: '均分', type: 'bar', data: byClass.value.map((c2) => c2.mean || 0), barWidth: 28, itemStyle: { color: c.primary, borderRadius: [6, 6, 0, 0] } },
      { name: '人数', type: 'line', data: byClass.value.map((c2) => c2.count || 0), smooth: true, symbolSize: 6, itemStyle: { color: c.cyan } },
    ],
  })
}

function renderQuestion(el: HTMLElement) {
  const c = chartColors()
  ensureChart(el).setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 40, top: 16, bottom: 26 },
    xAxis: { type: 'category', data: byQuestion.value.map((q) => `题${q.question_no}`), axisLabel: { color: c.ink500 } },
    yAxis: [
      { type: 'value', name: '均分', splitLine: { lineStyle: { color: c.lineLight } }, axisLabel: { color: c.ink500 } },
      { type: 'value', name: '得分率', max: 1, min: 0, axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, color: c.ink500 }, splitLine: { show: false } },
    ],
    series: [
      { name: '均分', type: 'bar', data: byQuestion.value.map((q) => q.mean || 0), barWidth: 22, itemStyle: { color: c.primary, borderRadius: [6, 6, 0, 0] } },
      { name: '得分率', type: 'line', yAxisIndex: 1, data: byQuestion.value.map((q) => q.score_rate || 0), smooth: true, symbolSize: 6, itemStyle: { color: c.amber } },
    ],
  })
}

function renderAll() {
  if (!summary.value?.count) return
  const distEl = document.getElementById('dist')
  const classEl = document.getElementById('class')
  const qEl = document.getElementById('q')
  if (distEl) renderDist(distEl)
  if (classEl) renderClass(classEl)
  if (qEl) renderQuestion(qEl)
}

function onThemeChange() {
  renderAll()
}

onMounted(async () => {
  loading.value = true
  try {
    const [s, cl, q] = await Promise.all([
      statsApi.paperSummary(paperId),
      statsApi.paperByClass(paperId),
      statsApi.paperByQuestion(paperId),
    ])
    summary.value = s
    byClass.value = cl
    byQuestion.value = q
    renderAll()
  } finally {
    loading.value = false
  }
  window.addEventListener('theme-change', onThemeChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('theme-change', onThemeChange)
})
</script>

<template>
  <div class="zh-page stats">
    <div class="page-bar">
      <h2 class="page-title">成绩统计 · 试卷 #{{ paperId }}</h2>
    </div>

    <div v-loading="loading">
      <!-- 汇总卡片 -->
      <div v-if="summary && summary.count" class="sum-cards">
        <div class="sum-card">
          <div class="sum-num num">{{ summary.count }}</div>
          <div class="sum-label">参测人数</div>
        </div>
        <div class="sum-card">
          <div class="sum-num num blue">{{ summary.mean }}</div>
          <div class="sum-label">平均分</div>
        </div>
        <div class="sum-card">
          <div class="sum-num num green">{{ summary.max }}</div>
          <div class="sum-label">最高分</div>
        </div>
        <div class="sum-card">
          <div class="sum-num num amber">{{ summary.min }}</div>
          <div class="sum-label">最低分</div>
        </div>
      </div>

      <div v-if="summary && summary.count" class="charts">
        <section class="zh-card">
          <h3 class="zh-section-title">分数段分布</h3>
          <div id="dist" class="chart" />
        </section>
        <section class="zh-card">
          <h3 class="zh-section-title">班级对比 · 均分与人数</h3>
          <div id="class" class="chart" />
        </section>
        <section class="zh-card wide">
          <h3 class="zh-section-title">逐题得分 · 均分与得分率（黄色线为得分率）</h3>
          <div id="q" class="chart" />
        </section>
      </div>

      <div v-else-if="!loading" class="empty-wrap">
        <EmptyState
          icon="chart"
          title="暂无成绩数据"
          :desc="summary ? '该卷尚无人完成批阅，或尚未生成成绩' : '无法加载该试卷统计'"
          height="360px"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats { max-width: 1280px; margin: 0 auto; }
.page-bar { margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 700; color: var(--ink-950); margin: 0; }
.sum-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; }
.sum-card { background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--radius-card); padding: 18px 20px; }
.sum-num { font-size: 30px; font-weight: 700; color: var(--ink-950); }
.sum-num.blue { color: var(--blue-600); }
.sum-num.green { color: var(--green-500); }
.sum-num.amber { color: var(--amber-500); }
.sum-label { font-size: 12px; color: var(--ink-500); margin-top: 6px; }
.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.charts .wide { grid-column: 1 / -1; }
.chart { height: 280px; }
.empty-wrap { padding: 40px 0; }
</style>