<script setup lang="ts">
import { computed } from 'vue'
import type { ScheduleEntry } from '@zhiheng/shared'

const props = withDefaults(defineProps<{
  entries: ScheduleEntry[]
  periods?: number
  dateMode?: boolean
  weekStart?: string
}>(), { periods: 8, dateMode: false, weekStart: '' })

const weekdayLabels = ['周一', '周二', '周三', '周四', '周五']
const headers = computed(() => weekdayLabels.map((label, index) => {
  const item = props.entries.find((entry) => entry.weekday === index + 1 && entry.lesson_date)
  let date = item?.lesson_date
  if (!date && props.dateMode && props.weekStart) {
    const day = new Date(`${props.weekStart}T00:00:00`)
    day.setDate(day.getDate() + index)
    date = [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-')
  }
  return { label, date: date?.slice(5) }
}))

function lesson(weekday: number, period: number) {
  return props.entries.find((entry) => entry.weekday === weekday && entry.period === period)
}
</script>

<template>
  <div class="schedule-wrap" role="region" aria-label="课程表" tabindex="0">
    <div class="schedule-grid">
      <div class="corner-cell"><span>节次</span><small>时间</small></div>
      <div v-for="header in headers" :key="header.label" class="day-head">
        <strong>{{ header.label }}</strong>
        <small v-if="dateMode">{{ header.date || '—' }}</small>
      </div>
      <template v-for="period in periods" :key="period">
        <div class="period-cell"><strong>{{ period }}</strong><small>第 {{ period }} 节</small></div>
        <div v-for="weekday in 5" :key="`${weekday}-${period}`" class="lesson-cell" :class="{ filled: lesson(weekday, period) }">
          <template v-if="lesson(weekday, period)">
            <strong>{{ lesson(weekday, period)?.subject_name }}</strong>
            <span>{{ lesson(weekday, period)?.teacher_name }}</span>
            <small v-if="lesson(weekday, period)?.room">{{ lesson(weekday, period)?.room }}</small>
          </template>
          <span v-else class="empty-mark">—</span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.schedule-wrap { overflow:auto; border:1px solid var(--line); background:#fff; }
.schedule-grid { min-width:840px; display:grid; grid-template-columns:88px repeat(5,1fr); }
.corner-cell,.day-head,.period-cell,.lesson-cell { min-height:76px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }
.corner-cell,.day-head,.period-cell { display:flex; flex-direction:column; align-items:center; justify-content:center; background:#f7f9fc; }
.corner-cell span,.period-cell strong { color:var(--ink-950); font-size:13px; }
.corner-cell small,.period-cell small,.day-head small { margin-top:4px; color:var(--ink-500); font-size:10px; }
.day-head { min-height:54px; border-top:3px solid var(--graphite-950); }
.day-head strong { color:var(--ink-950); font-size:13px; }
.lesson-cell { padding:11px 12px; display:flex; flex-direction:column; justify-content:center; background:#fff; }
.lesson-cell.filled { border-left:3px solid var(--blue-600); background:#f8fbff; }
.lesson-cell strong { color:var(--ink-950); font-size:13px; }
.lesson-cell span { margin-top:5px; color:var(--ink-500); font-size:11px; }
.lesson-cell small { margin-top:3px; color:var(--blue-600); font-size:10px; }
.empty-mark { align-self:center; color:#d4dae3!important; }
.schedule-grid > :nth-child(6n) { border-right:0; }
@media print { .schedule-wrap { overflow:visible; border-color:#999; } .schedule-grid { min-width:0; } }
</style>
