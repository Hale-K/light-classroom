<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance } from 'element-plus'
import Icon from '@/components/Icon.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaperBookLibrary from '@/components/PaperBookLibrary.vue'
import { examApi, orgApi } from '@zhiheng/api'
import {
  DIFFICULTY_LABEL,
  EXAM_STATUS_LABEL,
  EXAM_TYPE_LABEL,
  PAPER_STATUS_LABEL,
  type Exam,
  type Grade,
  type Paper,
} from '@zhiheng/shared'

const router = useRouter()
const loading = ref(false)
const exams = ref<Exam[]>([])
const filter = ref('')
const grades = ref<Grade[]>([])

// 学科演示映射：真实系统可有 subject 表；此处以固定 id 对应常见科目
const SUBJECTS = [
  { id: 1, name: '语文' },
  { id: 2, name: '数学' },
  { id: 3, name: '英语' },
  { id: 4, name: '物理' },
  { id: 5, name: '化学' },
  { id: 6, name: '生物' },
  { id: 7, name: '政治' },
  { id: 8, name: '历史' },
  { id: 9, name: '地理' },
]

const filteredExams = computed(() =>
  filter.value ? exams.value.filter((e) => e.status === filter.value) : exams.value,
)

const statusTag = (s?: string) =>
  ({ preparing: 'info', ongoing: 'primary', ended: 'success', archived: 'warning' })[s as string] ||
  'info'

async function loadExams() {
  loading.value = true
  try {
    exams.value = await examApi.list()
  } finally {
    loading.value = false
  }
}

// ---------- 新建考试 ----------
const examDlg = reactive({ visible: false, saving: false })
const examFormRef = ref<FormInstance>()
const examForm = reactive({ name: '', exam_type: 'monthly', academic_year: '' })

function openExamDlg() {
  const now = new Date().getFullYear()
  examForm.academic_year = `${now}-${now + 1}`
  examDlg.visible = true
}
async function saveExam() {
  examDlg.saving = true
  try {
    await examApi.create(examForm)
    ElMessage.success('考试已创建')
    examDlg.visible = false
    loadExams()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    examDlg.saving = false
  }
}

async function changeStatus(exam: Exam, status: string) {
  await examApi.updateStatus(exam.id, status)
  ElMessage.success('状态已更新')
  loadExams()
}

// ---------- 试卷管理抽屉 ----------
const drawer = reactive({ visible: false, exam: null as Exam | null, papers: [] as Paper[], loading: false })
async function openPapers(exam: Exam) {
  drawer.exam = exam
  drawer.visible = true
  drawer.loading = true
  try {
    const detail = await examApi.detail(exam.id)
    drawer.papers = detail.papers || []
  } finally {
    drawer.loading = false
  }
}
async function reloadPapers() {
  if (!drawer.exam) return
  const detail = await examApi.detail(drawer.exam.id)
  drawer.papers = detail.papers || []
}

const paperPreview = reactive({
  visible: false,
  loading: false,
  paper: null as Paper | null,
})

async function openPaperPreview(paper: Paper) {
  paperPreview.paper = paper
  paperPreview.visible = true
  paperPreview.loading = true
  try {
    paperPreview.paper = await examApi.paper(paper.id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    paperPreview.loading = false
  }
}

function continuePreviewPaper() {
  if (!paperPreview.paper || !drawer.exam) return
  const paper = paperPreview.paper
  paperPreview.visible = false
  openNewPaper(drawer.exam, paper)
}

// ---------- 新建 / 编辑试卷（轻量建卷） ----------
const paperDlg = reactive({
  visible: false,
  saving: false,
  examId: 0,
  form: { title: '', subject_id: 2, grade_id: 0, total_score: 100 },
  // 题目编辑
  editingPaper: null as (Paper & { questions?: Array<{ id: number; question_no: number; score: number; difficulty?: string | null; content?: string | null }> }) | null,
})
const paperFormRef = ref<FormInstance>()

async function openNewPaper(exam: Exam, paper?: Paper) {
  paperDlg.examId = exam.id
  paperDlg.visible = true
  drawer.visible = false
  if (paper) {
    paperDlg.form = { title: paper.title, subject_id: paper.subject_id || 2, grade_id: paper.grade_id || grades.value[0]?.id || 0, total_score: paper.total_score || 100 }
    const fresh = await examApi.paper(paper.id)
    paperDlg.editingPaper = fresh as typeof paperDlg.editingPaper
  } else {
    paperDlg.editingPaper = null
    paperDlg.form = { title: `${exam.name} 试卷`, subject_id: 2, grade_id: grades.value[0]?.id || 0, total_score: 100 }
  }
}

const newQ = reactive({ score: 0, difficulty: 'basic', content: '' })
const draftQuestions = ref<Array<{ score: number; difficulty: string; content: string }>>([])

async function savePaper() {
  paperDlg.saving = true
  try {
    let paper: Paper
    if (paperDlg.editingPaper) {
      paper = paperDlg.editingPaper
    } else {
      paper = await examApi.createPaper(paperDlg.examId, {
        title: paperDlg.form.title,
        subject_id: paperDlg.form.subject_id,
        grade_id: paperDlg.form.grade_id,
        total_score: paperDlg.form.total_score,
      })
      paperDlg.editingPaper = paper as Paper & {
        questions?: Array<{ id: number; question_no: number; score: number; difficulty?: string | null; content?: string | null }>
      }
      ElMessage.success('试卷已创建，可继续添加题目')
    }
    // 提交题目
    if (paperDlg.editingPaper) {
      for (const q of draftQuestions.value) {
        await examApi.addQuestion(paperDlg.editingPaper.id, {
          score: q.score,
          difficulty: q.difficulty,
          content: q.content || null,
        })
      }
      draftQuestions.value = []
      ElMessage.success(`已保存 ${paper.id} 号题`)
      // 重新拉取题目
      const fresh = await examApi.paper(paper.id)
      paperDlg.editingPaper = fresh as typeof paperDlg.editingPaper
    }
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    paperDlg.saving = false
  }
}

function addDraft() {
  draftQuestions.value.push({ ...newQ })
  newQ.score = 0
  newQ.content = ''
}

function removeDraft(i: number) {
  draftQuestions.value.splice(i, 1)
}

function finalizePaper() {
  if (!paperDlg.editingPaper) return
  ElMessageBox.confirm('定稿后试卷不可再增改题目，确定定稿吗？', '定稿确认', {
    type: 'warning',
    confirmButtonText: '定稿',
  }).then(async () => {
    await examApi.finalizePaper(paperDlg.editingPaper!.id)
    ElMessage.success('试卷已定稿')
    paperDlg.visible = false
    drawer.visible = true
    reloadPapers()
  }).catch(() => {})
}

function goGrading(p: Paper) { router.push(`/grading/${p.id}`) }
function goStats(p: Paper) { router.push(`/stats/${p.id}`) }

onMounted(async () => {
  loadExams()
  grades.value = await orgApi.grades()
})
</script>

<template>
  <div class="zh-page">
    <div class="page-bar">
      <h2 class="page-title">考试与建卷</h2>
      <el-button type="primary" @click="openExamDlg"><Icon name="calendar" :size="16" />&nbsp;新建考试</el-button>
    </div>

    <div class="zh-card">
      <div class="toolbar">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="ongoing">进行中</el-radio-button>
          <el-radio-button value="preparing">筹备中</el-radio-button>
          <el-radio-button value="ended">已结束</el-radio-button>
        </el-radio-group>
      </div>
      <el-table v-loading="loading" :data="filteredExams" style="width: 100%">
        <el-table-column label="考试名称" min-width="200">
          <template #default="{ row }">
            <span class="exam-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ EXAM_TYPE_LABEL[row.exam_type] || '月考' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="学年" width="120">
          <template #default="{ row }"><span class="ink500">{{ row.academic_year }}</span></template>
        </el-table-column>
        <el-table-column label="试卷" width="70" align="center">
          <template #default="{ row }"><span class="num">{{ row.paper_count ?? 0 }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ EXAM_STATUS_LABEL[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openPapers(row)">试卷</el-button>
            <el-button v-if="row.status === 'preparing'" size="small" type="primary" @click="openNewPaper(row)">建卷</el-button>
            <el-dropdown v-else size="small" trigger="click" @command="(c: string) => changeStatus(row, c)">
              <el-button size="small">改状态</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="ongoing">设为进行中</el-dropdown-item>
                  <el-dropdown-item command="ended">设为已结束</el-dropdown-item>
                  <el-dropdown-item command="archived">归档</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState icon="calendar" title="暂无考试" desc="点击右上角「新建考试」开始流程" :height="180" action-text="新建考试" @action="openExamDlg" />
        </template>
      </el-table>
    </div>

    <!-- 新建考试 -->
    <el-dialog v-model="examDlg.visible" title="新建考试" width="420px">
      <el-form ref="examFormRef" :model="examForm" label-width="70px">
        <el-form-item label="考试名称" required>
          <el-input v-model="examForm.name" placeholder="如：高三月考（一）" maxlength="100" />
        </el-form-item>
        <el-form-item label="考试类型">
          <el-select v-model="examForm.exam_type" style="width: 100%">
            <el-option v-for="(label, val) in EXAM_TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
        <el-form-item label="学年">
          <el-input v-model="examForm.academic_year" placeholder="如：2026-2027" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="examDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="examDlg.saving" :disabled="!examForm.name" @click="saveExam">创建</el-button>
      </template>
    </el-dialog>

    <!-- 试卷管理 -->
    <el-drawer v-model="drawer.visible" :title="`${drawer.exam?.name || ''} · 试卷书架`" size="min(820px, 92vw)">
      <PaperBookLibrary
        :key="drawer.exam?.id"
        :papers="drawer.papers"
        :loading="drawer.loading"
        :subjects="SUBJECTS"
        @create="drawer.exam && openNewPaper(drawer.exam)"
        @open="openPaperPreview"
      />
    </el-drawer>

    <el-dialog v-model="paperPreview.visible" width="min(820px, 92vw)" class="paper-preview-dialog" :show-close="true">
      <template #header><span class="preview-heading">试卷详情</span></template>
      <div v-loading="paperPreview.loading" class="open-paper">
        <section class="paper-page paper-overview">
          <span class="preview-subject">{{ SUBJECTS.find(item => item.id === paperPreview.paper?.subject_id)?.name || '未分类' }}</span>
          <h2>{{ paperPreview.paper?.title }}</h2>
          <div class="preview-rule" />
          <dl>
            <div><dt>满分</dt><dd>{{ paperPreview.paper?.total_score || 0 }}</dd></div>
            <div><dt>题目</dt><dd>{{ paperPreview.paper?.questions?.length || 0 }}</dd></div>
            <div><dt>状态</dt><dd>{{ PAPER_STATUS_LABEL[paperPreview.paper?.status || ''] || paperPreview.paper?.status }}</dd></div>
          </dl>
        </section>
        <section class="paper-page question-page">
          <div class="question-page-head"><strong>题目目录</strong><span>按题号顺序</span></div>
          <div v-if="paperPreview.paper?.questions?.length" class="preview-questions">
            <div v-for="question in paperPreview.paper.questions" :key="question.id" class="preview-question">
              <b>{{ question.question_no }}</b>
              <span>{{ question.content || '未填写题干' }}</span>
              <small>{{ DIFFICULTY_LABEL[question.difficulty || ''] || '基础' }} · {{ question.score }} 分</small>
            </div>
          </div>
          <div v-else class="preview-empty">这本试卷还没有题目</div>
        </section>
      </div>
      <template #footer>
        <el-button @click="paperPreview.visible=false">合上试卷</el-button>
        <template v-if="paperPreview.paper?.status === 'finalized'">
          <el-button @click="paperPreview.paper && goGrading(paperPreview.paper)">进入打分</el-button>
          <el-button type="primary" @click="paperPreview.paper && goStats(paperPreview.paper)">查看成绩</el-button>
        </template>
        <el-button v-else type="primary" @click="continuePreviewPaper">继续建卷</el-button>
      </template>
    </el-dialog>

    <!-- 轻量建卷 -->
    <el-dialog v-model="paperDlg.visible" title="轻量建卷" width="640px" @closed="draftQuestions = []">
      <el-form ref="paperFormRef" :model="paperDlg.form" label-width="80px">
        <el-form-item label="试卷标题" required>
          <el-input v-model="paperDlg.form.title" maxlength="200" />
        </el-form-item>
        <div class="form-row">
          <el-form-item label="科目">
            <el-select v-model="paperDlg.form.subject_id">
              <el-option v-for="s in SUBJECTS" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="年级">
            <el-select v-model="paperDlg.form.grade_id" placeholder="选择年级">
              <el-option v-for="g in grades" :key="g.id" :label="g.name" :value="g.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="满分">
            <el-input-number v-model="paperDlg.form.total_score" :min="1" :max="200" />
          </el-form-item>
        </div>
      </el-form>

      <el-divider content-position="left">题目清单</el-divider>
      <div class="question-editor">
        <div v-if="paperDlg.editingPaper?.questions?.length" class="q-list">
          <div v-for="q in paperDlg.editingPaper.questions" :key="q.id" class="q-row">
            <span class="q-no num">{{ q.question_no }}</span>
            <el-tag size="small" effect="plain">{{ DIFFICULTY_LABEL[q.difficulty || ''] || '基础' }}</el-tag>
            <span class="q-content">{{ q.content || '（无题干）' }}</span>
            <span class="q-score num">{{ q.score }} 分</span>
          </div>
        </div>
        <div class="q-add">
          <span class="q-desc">新增题目（默认自动续号）</span>
          <div class="q-add-row">
            <el-input-number v-model="newQ.score" :min="0" :max="200" placeholder="分值" controls-position="right" style="width: 120px" />
            <el-select v-model="newQ.difficulty" style="width: 100px">
              <el-option v-for="(label, val) in DIFFICULTY_LABEL" :key="val" :label="label" :value="val" />
            </el-select>
            <el-input v-model="newQ.content" placeholder="题干/知识点要点（可选）" clearable />
            <el-button @click="addDraft">添加</el-button>
          </div>
          <div v-for="(q, i) in draftQuestions" :key="i" class="q-row draft">
            <el-tag size="small" effect="plain" type="warning">草稿</el-tag>
            <span class="q-content">{{ q.content || '（无题干）' }}</span>
            <span class="q-score num">{{ q.score }} 分</span>
            <el-button text type="danger" size="small" @click="removeDraft(i)">移除</el-button>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="paperDlg.visible = false">关闭</el-button>
        <el-button :loading="paperDlg.saving" @click="savePaper">保存题目</el-button>
        <el-button v-if="paperDlg.editingPaper" type="success" @click="finalizePaper">定稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 700; color: var(--ink-950); margin: 0; }
.toolbar {}
.exam-name { font-weight: 500; color: var(--ink-950); }
.ink500 { color: var(--ink-500); font-size: 13px; }

.drawer-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-size: 13px; color: var(--ink-500); }
.paper-list { display: flex; flex-direction: column; gap: 10px; min-height: 200px; }
.paper-item {
  display: flex; align-items: center; justify-content: space-between;
  border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px;
}
.paper-title { font-weight: 600; color: var(--ink-950); margin-bottom: 4px; }
.paper-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-500); }

.form-row { display: flex; gap: 12px; }
.form-row :deep(.el-form-item) { flex: 1; }

.question-editor { display: flex; flex-direction: column; gap: 12px; }
.q-list { display: flex; flex-direction: column; gap: 8px; }
.q-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; background: var(--surface-0); border-radius: 8px; font-size: 13px;
}
.q-no { width: 26px; height: 26px; border-radius: 6px; background: var(--blue-100); color: var(--blue-600); font-weight: 600; display: grid; place-items: center; }
.q-content { flex: 1; color: var(--ink-700); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.q-score { color: var(--ink-950); font-weight: 600; }
.q-row.draft { background: var(--surface-2); }
.q-desc { font-size: 12px; color: var(--ink-500); }
.q-add-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.preview-heading{font-size:13px;font-weight:700;letter-spacing:.08em;color:var(--ink-500)}.open-paper{position:relative;display:grid;grid-template-columns:1fr 1fr;min-height:430px;overflow:hidden;border:1px solid #cec5b7;background:#f5f0e7;box-shadow:0 22px 45px rgba(27,30,33,.18);transform-origin:center center;animation:open-book .48s cubic-bezier(.2,.8,.2,1)}.open-paper:after{content:"";position:absolute;top:0;bottom:0;left:50%;width:1px;background:#c9bfae;box-shadow:-5px 0 12px rgba(60,48,33,.08),5px 0 12px rgba(60,48,33,.08)}.paper-page{min-width:0;padding:38px 34px;background:linear-gradient(90deg,rgba(110,95,72,.03) 1px,transparent 1px),#f7f2e9;background-size:24px 100%}.paper-overview{display:flex;flex-direction:column}.preview-subject{font-size:10px;letter-spacing:.18em;color:#796b59}.paper-overview h2{max-width:300px;margin:42px 0 0;font-family:"Noto Serif SC","Songti SC",serif;font-size:28px;line-height:1.45;color:#27231e}.preview-rule{width:44px;height:1px;margin-top:24px;background:#8b7d69}.paper-overview dl{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:auto 0 0}.paper-overview dl div{border-top:1px solid #d8cdbc;padding-top:10px}.paper-overview dt{font-size:10px;color:#8b7e6d}.paper-overview dd{margin:5px 0 0;font-family:Georgia,serif;font-size:18px;color:#2c2822}.question-page{overflow-y:auto;max-height:520px}.question-page-head{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid #d8cdbc;padding-bottom:12px}.question-page-head strong{font-family:"Noto Serif SC","Songti SC",serif;color:#29251f}.question-page-head span{font-size:10px;color:#8b7e6d}.preview-questions{display:flex;flex-direction:column}.preview-question{display:grid;grid-template-columns:26px minmax(0,1fr);gap:5px 10px;padding:14px 0;border-bottom:1px solid #e0d7ca}.preview-question b{grid-row:1/3;color:#675b4b}.preview-question span{overflow:hidden;color:#39342d;font-size:12px;line-height:1.5;text-overflow:ellipsis;white-space:nowrap}.preview-question small{color:#8b7e6d;font-size:10px}.preview-empty{display:grid;place-items:center;min-height:260px;color:#8b7e6d;font-size:12px}@keyframes open-book{from{opacity:0;transform:perspective(1200px) rotateY(-14deg) scale(.94)}to{opacity:1;transform:perspective(1200px) rotateY(0) scale(1)}}@media(max-width:680px){.open-paper{grid-template-columns:1fr}.open-paper:after{display:none}.paper-page{padding:28px 22px}.paper-overview{min-height:330px}.form-row{flex-direction:column}}
</style>
