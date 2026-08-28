<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import Icon from '@/components/Icon.vue'
import EmptyState from '@/components/EmptyState.vue'
import { gradingApi } from '@zhiheng/api'

/** 队列项：一名学生的作答 */
interface SubmissionItem {
  id: number
  student_name?: string | null
  status?: string
  total_score?: number
}
/** 单题评分项 */
interface GradingQuestion {
  question_id: number
  question_no: number
  score: number
  difficulty?: string | null
  content?: string | null
  given_score: number | null
  ai_score: number | null
  ai_confidence: number | null
}
/** 当前批阅详情 */
interface GradingDetail {
  submission: { id: number; status?: string; total_score?: number } | null
  student_name?: string | null
  questions: GradingQuestion[]
}

const route = useRoute()
const paperId = Number(route.params.paperId)

const loading = ref(true)
const submissions = ref<SubmissionItem[]>([])
const currentSubId = ref<number | null>(null)

const detail = reactive<GradingDetail>({ submission: null, questions: [] })

const currentIdx = ref(0)
const scores = reactive<Record<string, number | null>>({})

const currentSub = computed(() => submissions.value[currentIdx.value])
const gradedCount = computed(() => submissions.value.filter((s) => s.status === 'graded').length)

async function loadQueue() {
  loading.value = true
  try {
    submissions.value = await gradingApi.queue(paperId)
    currentIdx.value = 0
    // 定位到第一位未批阅的学生
    const nextIdx = submissions.value.findIndex((s) => s.status !== 'graded')
    currentIdx.value = nextIdx >= 0 ? nextIdx : 0
    await loadDetail()
  } finally {
    loading.value = false
  }
}

async function loadDetail() {
  const sub = currentSub.value
  if (!sub) {
    detail.submission = null
    detail.questions = []
    scores.__ = null
    return
  }
  currentSubId.value = sub.id
  loading.value = true
  try {
    const d = await gradingApi.detail(sub.id)
    detail.submission = d.submission
    detail.student_name = d.student_name
    detail.questions = d.questions
    d.questions.forEach((q) => {
      scores[q.question_id] = q.given_score
    })
  } finally {
    loading.value = false
  }
}

const totalScore = computed(() => detail.questions.reduce((s, q) => s + (Number(scores[q.question_id]) || 0), 0))
const answeredCount = computed(() => detail.questions.filter((q) => scores[q.question_id] != null).length)

async function saveScore(qid: number, val: number) {
  if (currentSubId.value == null) return
  try {
    await gradingApi.score(currentSubId.value, qid, val)
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function nextQuestion() {
  const input = document.querySelector<HTMLElement>('.sp-body .el-input input')
  if (input) input.focus()
}

function submitAndNext() {
  const sub = currentSub.value
  if (!sub) return
  ElMessageBox.confirm(
    `是否提交「${detail.student_name || `#${sub.id}`}」并汇总总分（当前 ${answeredCount.value}/${detail.questions.length} 题 / ${totalScore.value} 分）？`,
    '提交本份',
    { type: 'warning', confirmButtonText: '提交', cancelButtonText: '继续批改' },
  ).then(async () => {
    await gradingApi.finalize(sub.id)
    await loadQueue()
    if (submissions.value.length && currentSub.value?.status === 'graded') {
      // 自动跳到下一份待批
      loadQueue()
    }
    ElMessage.success('已提交下一份')
  }).catch(() => {})
}

function jumpTo(i: number) {
  if (i < 0 || i >= submissions.value.length) return
  currentIdx.value = i
  loadDetail()
}

// 键盘流
function onKey(e: KeyboardEvent) {
  // 避免与输入框内打字冲突
  const tag = (e.target as HTMLElement)?.tagName
  if ((tag === 'INPUT' || tag === 'TEXTAREA') && e.key !== 'Enter' && e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  if (e.key === 'Enter') {
    e.preventDefault()
    // 满分配下一个未答，否则切下一份
    const nextUnanswered = detail.questions.find((q) => scores[q.question_id] == null)
    if (nextUnanswered) {
      scores[nextUnanswered.question_id] = nextUnanswered.score
      saveScore(nextUnanswered.question_id, nextUnanswered.score)
      ElMessage({ message: `第 ${nextUnanswered.question_no} 题 满分`, type: 'success', duration: 800 })
    } else {
      nextQuestion()
    }
  }
  if (e.key === 'ArrowDown' || e.key === ']') jumpTo(currentIdx.value + 1)
  if (e.key === 'ArrowUp' || e.key === '[') jumpTo(currentIdx.value - 1)
}

onMounted(async () => {
  await loadQueue()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

watch(currentIdx, (i) => {
  if (i >= 0 && i < submissions.value.length) loadDetail()
})
</script>

<template>
  <div v-loading="loading" class="grading">
    <!-- 工具条 -->
    <div class="gbar">
      <div class="gbar-left">
        <span class="gfile"><Icon name="keyboard" :size="16" />&nbsp;打分工作台</span>
        <span class="gsep" />
        <span class="gmeta">试卷 #{{ paperId }}</span>
        <span class="gmeta">已批 {{ gradedCount }}/{{ submissions.length }}</span>
      </div>
      <div class="gbar-right">
        <el-button size="small" text @click="jumpTo(currentIdx - 1)" :disabled="currentIdx <= 0">上一份</el-button>
        <span class="gidx num">{{ currentIdx + 1 }}/{{ submissions.length }}</span>
        <el-button size="small" text @click="jumpTo(currentIdx + 1)" :disabled="currentIdx >= submissions.length - 1">下一份</el-button>
        <el-button size="small" type="success" :disabled="!detail.submission" @click="submitAndNext">提交本份</el-button>
      </div>
    </div>

    <div v-if="!submissions.length && !loading" class="empty-wrap">
      <EmptyState icon="keyboard" title="没有待批阅的作答" desc="请先在「扫描进卷」为试卷分配并确认学生作答" height="100%" />
    </div>

    <div v-else class="gbody">
      <!-- 左：卷面（真实题目渲染为可读卷） -->
      <section class="sheet">
        <div class="sheet-head">
          <div>
            <div class="sheet-student">{{ detail.student_name || '考生' }}的答卷</div>
            <div class="sheet-sub">双击题区可放大 · 数字键/Enter 给分</div>
          </div>
          <div class="sheet-tools">
            <button class="tool" title="旋转"><Icon name="rotate" :size="18" /></button>
            <button class="tool" title="放大"><Icon name="zoom-in" :size="18" /></button>
          </div>
        </div>
        <div class="sheet-body">
          <div class="sheet-page">
            <div
              v-for="q in detail.questions"
              :key="q.question_id"
              class="q-block"
              :class="{ done: scores[q.question_id] != null }"
            >
              <span class="qb-no num">{{ q.question_no }}</span>
              <div class="qb-main">
                <div class="qb-content">{{ q.content || '（无题干，请结合扫描卷面给分）' }}</div>
                <div class="qb-scoreline">
                  <span class="qb-full">满分 {{ q.score }} 分</span>
                  <el-tag v-if="scores[q.question_id] != null" size="small" effect="plain" type="success">已给分 {{ scores[q.question_id] }}</el-tag>
                </div>
              </div>
            </div>
            <div v-if="!detail.questions.length" class="no-q">该试卷尚未建题</div>
          </div>
        </div>
      </section>

      <!-- 右：评分面板（键盘流） -->
      <aside class="score-panel">
        <div class="sp-head">
          <span>逐题给分</span>
          <span class="sp-progress num">{{ answeredCount }}/{{ detail.questions.length }} · 小计 {{ totalScore }} 分</span>
        </div>
        <div class="sp-body">
          <div v-for="q in detail.questions" :key="q.question_id" class="sp-row">
            <span class="sp-no num">{{ q.question_no }}</span>
            <div class="sp-info">
              <div class="sp-content">{{ q.content || '（无题干）' }}</div>
              <div class="sp-meta">
                <span>满分 {{ q.score }}</span>
                <span v-if="q.ai_confidence != null" class="ai-badge"><Icon name="sparkles" :size="12" />AI {{ Math.round((q.ai_confidence || 0) * 100) }}%</span>
              </div>
            </div>
            <div class="sp-input">
              <el-input-number
                :model-value="scores[q.question_id]"
                :min="0"
                :max="q.score"
                controls-position="right"
                size="small"
                @update:model-value="(v: number | null) => { scores[q.question_id] = v; saveScore(q.question_id, Number(v || 0)) }"
              />
              <button class="full-btn" @click="scores[q.question_id] = q.score; saveScore(q.question_id, q.score)">满分</button>
            </div>
          </div>
        </div>
        <div class="sp-keys">
          <div class="key"><span>Enter</span><em>满分配下一未答题</em></div>
          <div class="key"><span>数字</span><em>直接键入得分</em></div>
          <div class="key"><span>[ / ]</span><em>上一份 / 下一份</em></div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.grading { height: 100%; display: flex; flex-direction: column; background: var(--surface-0); }
.gbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px; height: 52px; background: var(--surface-1); color: var(--ink-950); flex-shrink: 0; border-bottom: 1px solid var(--line);
}
.gbar-left { display: flex; align-items: center; gap: 14px; }
.gfile { display: flex; align-items: center; gap: 7px; font-weight: 600; color: var(--ink-950); font-size: 13px; }
.gfile :deep(svg) { color: var(--ink-500); }
.gmeta { color: var(--ink-400); font-size: 12px; }
.gsep { width: 1px; height: 16px; background: var(--line); }
.gbar-right { display: flex; align-items: center; gap: 6px; color: var(--ink-500); }
.gbar-right :deep(.el-button) { color: var(--ink-700); }
.gidx { min-width: 48px; text-align: center; }

.gbody {
  flex: 1; display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(380px, .85fr); gap: 12px; padding: 12px; min-height: 0;
}
.empty-wrap { flex: 1; display: flex; align-items: center; justify-content: center; padding: 40px; }

.sheet { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-card); display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.sheet-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--line); }
.sheet-student { font-weight: 600; color: var(--ink-950); }
.sheet-sub { font-size: 12px; color: var(--ink-500); margin-top: 2px; }
.sheet-tools { display: flex; gap: 6px; }
.tool { width: 32px; height: 32px; border: 1px solid var(--line); background: var(--surface-1); border-radius: 8px; color: var(--ink-500); display: grid; place-items: center; cursor: pointer; }
.tool:hover { color: var(--blue-600); background: var(--blue-100); }
.sheet-body { flex: 1; overflow: auto; padding: 20px 24px; }
.sheet-page { max-width: 820px; margin: 0 auto; background: #fff; border: 1px solid var(--line); border-radius: 4px; padding: 28px 32px; min-height: 100%; }
.q-block { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px dashed var(--line); }
.q-block.done { background: linear-gradient(90deg, #f6fdfa 0%, transparent 60%); border-radius: 8px; }
.qb-no { width: 28px; height: 28px; border-radius: 7px; background: var(--primary); color: #fff; display: grid; place-items: center; font-weight: 600; flex-shrink: 0; }
.q-block.done .qb-no { background: var(--green-500); }
.qb-main { flex: 1; }
.qb-content { color: var(--ink-700); line-height: 1.7; }
.qb-scoreline { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.qb-full { font-size: 12px; color: var(--ink-500); }
.no-q { color: var(--ink-500); text-align: center; padding: 40px; }

.score-panel { background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--radius-card); display: flex; flex-direction: column; min-height: 0; }
.sp-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 16px; border-bottom: 1px solid var(--line); font-weight: 700; color: var(--ink-950); }
.sp-progress { font-size: 12px; color: var(--ink-500); font-weight: 400; }
.sp-body { flex: 1; overflow: auto; padding: 8px 12px; }
.sp-row { display: grid; grid-template-columns: 28px 1fr 154px; gap: 10px; align-items: center; padding: 11px 4px; border-bottom: 1px solid var(--line); }
.sp-no { width: 24px; height: 24px; border-radius: 6px; background: var(--blue-100); color: var(--blue-600); display: grid; place-items: center; font-weight: 600; }
.sp-content { font-size: 13px; color: var(--ink-700); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sp-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-500); margin-top: 2px; }
.ai-badge { display: inline-flex; align-items: center; gap: 3px; color: var(--blue-600); }
.sp-input { display: flex; align-items: center; gap: 6px; }
.sp-input :deep(.el-input-number) { flex: 1; }
.sp-input :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--blue-600) inset!important; }
.full-btn { border: 1px solid var(--green-500); color: var(--green-500); background: #fff; border-radius: 6px; font-size: 12px; padding: 4px 8px; cursor: pointer; white-space: nowrap; }
.full-btn:hover { background: var(--green-500); color: #fff; }
.sp-keys { display: flex; align-items: center; gap: 16px; padding: 10px 16px; border-top: 1px solid var(--line); color: var(--ink-500); font-size: 12px; }
.key { display: flex; align-items: center; gap: 6px; }
.key span { border: 1px solid var(--line); border-radius: 5px; padding: 2px 7px; background: var(--surface-0); color: var(--ink-700); font-weight: 600; }
.key em { font-style: normal; }
</style>
