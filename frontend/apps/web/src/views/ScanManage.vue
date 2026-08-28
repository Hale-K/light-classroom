<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import Icon from '@/components/Icon.vue'
import EmptyState from '@/components/EmptyState.vue'
import { examApi, scanApi } from '@zhiheng/api'
import type { Exam, Paper, ScanBatch } from '@zhiheng/shared'

const router = useRouter()
const loading = ref(false)
const batches = ref<ScanBatch[]>([])
const papers = ref<Array<{ id: number; title: string; examName: string }>>([])

const batchStatusLabel = (s?: string) =>
  ({ uploaded: '已上传', split: '已切分', assigned: '已分配', confirmed: '已确认' })[s as string] || s || '未知'
const batchStatusTag = (s?: string) =>
  ({ uploaded: 'warning', split: 'primary', assigned: 'success', confirmed: 'info' })[s as string] || 'info'

function paperTitle(paperId: number) {
  const p = papers.value.find((x) => x.id === paperId)
  return p ? `${p.examName} / ${p.title}` : `试卷 #${paperId}`
}

async function loadBatches() {
  loading.value = true
  try {
    batches.value = await scanApi.batches()
  } finally {
    loading.value = false
  }
}

async function loadPapers() {
  const exams = await examApi.list()
  const list: Array<{ id: number; title: string; examName: string }> = []
  for (const exam of exams) {
    const detail: Exam & { papers: Paper[] } = await examApi.detail(exam.id)
    for (const p of detail.papers || []) {
      if (p.status === 'finalized') list.push({ id: p.id, title: p.title, examName: exam.name })
    }
  }
  papers.value = list
}

// 新建批次
const createDlg = reactive({ visible: false, saving: false })
const createForm = reactive({ paper_id: null as number | null, file_name: '', page_count: 0 })

function openCreate() {
  createForm.paper_id = papers.value[0]?.id || null
  createForm.file_name = ''
  createForm.page_count = 0
  createDlg.visible = true
}
async function saveBatch() {
  if (!createForm.paper_id) return ElMessage.warning('请选择试卷')
  createDlg.saving = true
  try {
    await scanApi.createBatch({
      paper_id: createForm.paper_id,
      file_name: createForm.file_name || undefined,
      page_count: createForm.page_count,
    })
    ElMessage.success('扫描批次已上传')
    createDlg.visible = false
    loadBatches()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    createDlg.saving = false
  }
}

// 流程动作
async function doSplit(b: ScanBatch) {
  await scanApi.split(b.id)
  ElMessage.success('已切分')
  loadBatches()
}
async function doAssign(b: ScanBatch) {
  try {
    const r = await scanApi.assign(b.id)
    ElMessage.success(`已分配 ${r.created}/${r.total} 名学生的作答`)
    loadBatches()
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}
function doConfirm(b: ScanBatch) {
  ElMessageBox.confirm('确认后将锁定该批次并进入打分流程，确定吗？', '确认批次', {
    type: 'warning',
    confirmButtonText: '确认',
  }).then(async () => {
    await scanApi.confirm(b.id)
    ElMessage.success('批次已确认')
    loadBatches()
  }).catch(() => {})
}
function doGrading(b: ScanBatch) {
  router.push(`/grading/${b.paper_id}`)
}
function doReload(b: ScanBatch) {
  ElMessage.info('真机可在此重新切分/矫正图像')
}

onMounted(async () => {
  await Promise.all([loadBatches(), loadPapers()])
})
</script>

<template>
  <div class="zh-page">
    <div class="page-bar">
      <div>
        <h2 class="page-title">扫描进卷</h2>
        <p class="page-desc">上传扫描件 → 切分 → 按名册分配学生作答 → 确认进入打分</p>
      </div>
      <el-button type="primary" @click="openCreate"><Icon name="upload" :size="16" />&nbsp;新建批次</el-button>
    </div>

    <div class="zh-card">
      <el-table v-loading="loading" :data="batches" style="width: 100%">
        <el-table-column label="批次" min-width="220">
          <template #default="{ row }">
            <div class="batch-cell">
              <span class="batch-icon"><Icon name="qrcode" :size="16" /></span>
              <div>
                <div class="batch-file">{{ row.file_name || `扫描批次 #${row.id}` }}</div>
                <div class="batch-paper text-ink500">{{ paperTitle(row.paper_id) }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="页数" width="80" align="center">
          <template #default="{ row }"><span class="num">{{ row.page_count ?? 0 }}</span></template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="batchStatusTag(row.status)">{{ batchStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }"><span class="ink500">{{ (row.created_at || '').slice(0, 10) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'uploaded'">
              <el-button size="small" @click="doReload(row)">页码矫正</el-button>
              <el-button size="small" type="primary" @click="doSplit(row)">切分</el-button>
            </template>
            <template v-else-if="row.status === 'split'">
              <el-button size="small" type="primary" @click="doAssign(row)">分配作答</el-button>
            </template>
            <template v-else-if="row.status === 'assigned'">
              <el-button size="small" @click="doGrading(row)">去打分</el-button>
              <el-button size="small" type="success" @click="doConfirm(row)">确认完成</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="doGrading(row)">去打分</el-button>
            </template>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState icon="scan" title="暂无扫描批次" desc="请先定稿试卷，再上传扫描件建立批次" :height="220" action-text="新建批次" @action="openCreate" />
        </template>
      </el-table>
    </div>

    <!-- 新建批次 -->
    <el-dialog v-model="createDlg.visible" title="上传扫描批次" width="480px">
      <el-form label-width="90px">
        <el-form-item label="所属试卷" required>
          <el-select v-model="createForm.paper_id" placeholder="选择已定稿试卷" filterable style="width: 100%">
            <el-option v-for="p in papers" :key="p.id" :label="`${p.examName} / ${p.title}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="批次名称">
          <el-input v-model="createForm.file_name" placeholder="可为空，默认自动命名" maxlength="255" />
        </el-form-item>
        <el-form-item label="页数">
          <el-input-number v-model="createForm.page_count" :min="0" :max="1000" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="createDlg.saving" :disabled="!createForm.paper_id" @click="saveBatch">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 700; color: var(--ink-950); margin: 0; }
.page-desc { font-size: 13px; color: var(--ink-500); margin: 6px 0 0; }
.batch-cell { display: flex; align-items: center; gap: 10px; }
.batch-icon { width: 32px; height: 32px; border-radius: 8px; background: var(--blue-100); color: var(--blue-600); display: grid; place-items: center; flex-shrink: 0; }
.batch-file { font-weight: 500; color: var(--ink-950); }
.batch-paper { font-size: 12px; margin-top: 2px; }
.ink500 { color: var(--ink-500); }
</style>