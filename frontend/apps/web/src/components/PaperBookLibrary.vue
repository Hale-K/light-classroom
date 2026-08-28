<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { gsap } from 'gsap'
import type { Paper } from '@zhiheng/shared'

const props = defineProps<{
  papers: Paper[]
  loading: boolean
  subjects: Array<{ id: number; name: string }>
}>()

const emit = defineEmits<{
  open: [paper: Paper]
  create: []
}>()

const root = ref<HTMLElement>()
const query = ref('')
const subjectId = ref<number | ''>('')
const palettes = ['#315c62', '#4a536f', '#73564a', '#536349', '#6f4d5b', '#4f5f78', '#675e45', '#3f6470', '#63506f']

const filteredPapers = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return props.papers.filter(paper => {
    const subject = props.subjects.find(item => item.id === paper.subject_id)?.name || ''
    const matchesKeyword = !keyword || paper.title.toLowerCase().includes(keyword) || subject.includes(keyword)
    return matchesKeyword && (subjectId.value === '' || paper.subject_id === subjectId.value)
  })
})

function subjectName(paper: Paper) {
  return props.subjects.find(item => item.id === paper.subject_id)?.name || '未分类'
}

function coverStyle(paper: Paper) {
  return { '--book-color': palettes[((paper.subject_id || 1) - 1) % palettes.length] }
}

async function animateBooks() {
  await nextTick()
  if (!root.value) return
  gsap.killTweensOf(root.value.querySelectorAll('.book-card'))
  gsap.fromTo(root.value.querySelectorAll('.book-card'), {
    opacity: 0,
    y: 34,
    rotateY: -12,
  }, {
    opacity: 1,
    y: 0,
    rotateY: 0,
    duration: .62,
    stagger: .055,
    ease: 'power3.out',
    clearProps: 'transform',
  })
}

function tiltBook(event: PointerEvent) {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const rotateY = ((event.clientX - rect.left) / rect.width - .5) * 9
  const rotateX = -((event.clientY - rect.top) / rect.height - .5) * 7
  gsap.to(target, { rotateX, rotateY, y: -8, duration: .25, ease: 'power2.out', transformPerspective: 900 })
}

function resetBook(event: PointerEvent | FocusEvent) {
  gsap.to(event.currentTarget as HTMLElement, { rotateX: 0, rotateY: 0, y: 0, duration: .42, ease: 'power3.out' })
}

function openBook(event: MouseEvent, paper: Paper) {
  const target = event.currentTarget as HTMLElement
  gsap.to(target, {
    scale: 1.035,
    rotateY: -7,
    duration: .18,
    yoyo: true,
    repeat: 1,
    ease: 'power2.inOut',
    onComplete: () => emit('open', paper),
  })
}

watch([() => props.papers, filteredPapers], animateBooks, { deep: true })
onBeforeUnmount(() => root.value && gsap.killTweensOf(root.value.querySelectorAll('*')))
</script>

<template>
  <section ref="root" class="paper-library" aria-label="试卷书架">
    <div class="library-tools">
      <el-input v-model="query" clearable placeholder="搜索试卷名称或学科" aria-label="搜索试卷">
        <template #prefix><span class="search-mark" aria-hidden="true" /></template>
      </el-input>
      <el-select v-model="subjectId" clearable placeholder="全部学科" aria-label="按学科筛选">
        <el-option v-for="subject in subjects" :key="subject.id" :label="subject.name" :value="subject.id" />
      </el-select>
      <el-button type="primary" @click="emit('create')">新建试卷</el-button>
    </div>

    <div v-loading="loading" class="shelves">
      <div v-if="filteredPapers.length" class="book-grid" role="list">
        <div v-for="paper in filteredPapers" :key="paper.id" class="shelf-slot" role="listitem">
          <button
            type="button"
            class="book-card"
            :style="coverStyle(paper)"
            :aria-label="`打开试卷：${paper.title}`"
            @pointermove="tiltBook"
            @pointerleave="resetBook"
          @blur="resetBook"
            @click="openBook($event, paper)"
          >
            <span class="book-pages" aria-hidden="true" />
            <span class="book-cover">
              <span class="book-spine" aria-hidden="true" />
              <span class="book-subject">{{ subjectName(paper) }}</span>
              <strong>{{ paper.title }}</strong>
              <span class="book-rule" aria-hidden="true" />
              <span class="book-meta">满分 {{ paper.total_score || 0 }}</span>
              <span class="book-status">{{ paper.status === 'finalized' ? '已定稿' : '建卷中' }}</span>
            </span>
          </button>
        </div>
      </div>
      <div v-else class="library-empty" role="status">
        <strong>{{ papers.length ? '没有找到匹配的试卷' : '书架还是空的' }}</strong>
        <span>{{ papers.length ? '换个名称或学科试试' : '新建试卷后，它会像一本书一样出现在这里' }}</span>
        <el-button v-if="!papers.length" type="primary" @click="emit('create')">新建第一本试卷</el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.paper-library{min-height:100%;font-family:Geist,"Microsoft YaHei",sans-serif}.library-tools{display:grid;grid-template-columns:minmax(240px,1fr) 150px auto;gap:10px;align-items:center;margin-bottom:18px}.search-mark{display:block;width:12px;height:12px;border:1.5px solid var(--ink-400);border-radius:50%;position:relative}.search-mark:after{content:"";position:absolute;width:5px;height:1.5px;right:-4px;bottom:-2px;transform:rotate(45deg);background:var(--ink-400)}.shelves{min-height:360px;padding:22px 18px 30px;border:1px solid var(--line);background:linear-gradient(90deg,rgba(20,28,36,.025) 1px,transparent 1px),var(--surface-0);background-size:28px 100%}.book-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:28px 20px;align-items:end}.shelf-slot{position:relative;display:flex;justify-content:center;padding-bottom:14px}.shelf-slot:after{content:"";position:absolute;right:-8px;bottom:0;left:-8px;height:10px;border-top:1px solid #a3937b;background:linear-gradient(180deg,#cab99f,#a89579);box-shadow:0 5px 9px rgba(35,29,22,.16)}.book-card{position:relative;width:142px;height:202px;padding:0;border:0;background:transparent;cursor:pointer;transform-style:preserve-3d;outline-offset:5px}.book-card:focus-visible{outline:2px solid var(--blue-600)}.book-pages{position:absolute;top:6px;right:-5px;bottom:3px;left:6px;border-radius:2px 5px 5px 2px;background:repeating-linear-gradient(90deg,#f5f0e7 0,#f5f0e7 3px,#ddd5c8 4px);box-shadow:5px 8px 14px rgba(20,24,29,.18)}.book-cover{position:absolute;inset:0;display:flex;flex-direction:column;align-items:flex-start;padding:20px 14px 16px 21px;overflow:hidden;border-radius:3px 7px 7px 3px;background:var(--book-color);color:#f9f5eb;text-align:left;box-shadow:inset 1px 0 rgba(255,255,255,.18),inset -3px 0 rgba(0,0,0,.13),0 12px 20px rgba(25,30,35,.18)}.book-cover:after{content:"";position:absolute;inset:0;background:linear-gradient(118deg,rgba(255,255,255,.14),transparent 31%,rgba(0,0,0,.1));pointer-events:none}.book-spine{position:absolute;top:0;bottom:0;left:8px;width:5px;border-right:1px solid rgba(255,255,255,.2);border-left:1px solid rgba(0,0,0,.16)}.book-subject{position:relative;font-size:10px;letter-spacing:.18em;opacity:.78}.book-cover strong{position:relative;margin-top:25px;font-family:"Noto Serif SC","Songti SC",serif;font-size:16px;line-height:1.45;display:-webkit-box;overflow:hidden;-webkit-line-clamp:4;-webkit-box-orient:vertical}.book-rule{position:relative;width:28px;height:1px;margin-top:auto;background:rgba(255,255,255,.55)}.book-meta,.book-status{position:relative;font-size:10px}.book-meta{margin-top:9px;opacity:.76}.book-status{position:absolute;right:11px;bottom:13px;padding:2px 5px;border:1px solid rgba(255,255,255,.35)}.library-empty{min-height:330px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--ink-500);text-align:center}.library-empty strong{color:var(--ink-950);font-size:15px}.library-empty span{margin:8px 0 18px;font-size:12px}@media(max-width:640px){.library-tools{grid-template-columns:1fr}.book-grid{grid-template-columns:repeat(2,minmax(130px,1fr));gap:24px 12px}.shelves{padding:18px 10px 26px}}
</style>
