<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { orgApi } from '@zhiheng/api'
import type { ClassInfo, Student } from '@zhiheng/shared'

const classes = ref<ClassInfo[]>([])
const students = ref<Student[]>([])
const keyword = ref('')
const classFilter = ref<number | 'unassigned' | ''>('')
const genderFilter = ref<'male' | 'female' | ''>('')
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const page = ref(1)
const pageSize = 10
const form = reactive({ name: '', student_no: '', gender: 'male', class_id: undefined as number | undefined, parent_phone: '', height_cm: undefined as number | undefined })
const filteredStudents = computed(() => students.value.filter((item) => {
  const query = keyword.value.trim().toLowerCase()
  const matchesKeyword = !query || item.name.toLowerCase().includes(query) || item.student_no?.toLowerCase().includes(query)
  const matchesClass = classFilter.value === ''
    || (classFilter.value === 'unassigned' ? !item.class_id : item.class_id === classFilter.value)
  const matchesGender = !genderFilter.value || item.gender === genderFilter.value
  return matchesKeyword && matchesClass && matchesGender
}))
const unassignedCount = computed(() => students.value.filter(item => !item.class_id).length)
const pagedStudents = computed(() => filteredStudents.value.slice((page.value - 1) * pageSize, page.value * pageSize))

watch([keyword, classFilter, genderFilter], () => { page.value = 1 })

function resetFilters() {
  keyword.value = ''
  classFilter.value = ''
  genderFilter.value = ''
}

async function loadData() {
  loading.value = true
  try {
    ;[classes.value, students.value] = await Promise.all([orgApi.classes(), orgApi.students()])
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '学生档案加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { name: '', student_no: '', gender: 'male', class_id: undefined, parent_phone: '', height_cm: undefined })
  dialogVisible.value = true
}

async function createStudent() {
  if (!form.name.trim()) return ElMessage.warning('请输入学生姓名')
  saving.value = true
  try {
    await orgApi.createStudent({
      name: form.name.trim(), student_no: form.student_no.trim() || undefined,
      gender: form.gender, class_id: form.class_id || null,
      parent_phone: form.parent_phone.trim() || undefined,
      height_cm: form.height_cm,
    })
    dialogVisible.value = false
    ElMessage.success(form.class_id ? '学生档案已创建' : '学生已加入待分班名单')
    await loadData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '学生创建失败')
  } finally {
    saving.value = false
  }
}

onMounted(loadData)
</script>

<template>
  <section class="students-page">
    <header class="page-header">
      <div><span class="eyebrow">STUDENT DIRECTORY</span><h1>学生档案</h1><p>先维护全校学生名册；学生可暂不指定行政班，随后进入“行政班管理”统一安排。</p></div>
      <el-button type="primary" @click="openCreate">新增学生</el-button>
    </header>
    <div class="summary"><span>学生总数 <strong>{{ students.length }}</strong></span><span>待分班 <strong>{{ unassignedCount }}</strong></span></div>
    <div class="toolbar" aria-label="学生搜索条件">
      <label class="filter-field"><span>学生</span><el-input v-model="keyword" clearable placeholder="姓名或学号" /></label>
      <label class="filter-field"><span>行政班</span><el-select v-model="classFilter" placeholder="全部班级" clearable><el-option label="待分班" value="unassigned" /><el-option v-for="item in classes" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
      <label class="filter-field"><span>性别</span><el-select v-model="genderFilter" placeholder="全部性别" clearable><el-option label="男" value="male" /><el-option label="女" value="female" /></el-select></label>
      <el-button class="reset-filter" @click="resetFilters">重置</el-button>
      <span class="count">当前 {{ filteredStudents.length }} 人</span>
    </div>
    <div class="table-shell" v-loading="loading">
      <el-table :data="pagedStudents" empty-text="暂无学生档案">
        <el-table-column prop="student_no" label="学号" min-width="150" />
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column label="行政班" min-width="150"><template #default="{ row }"><span :class="{ pending: !row.class_id }">{{ row.class_name || '待分班' }}</span></template></el-table-column>
        <el-table-column prop="gender" label="性别" width="90" />
        <el-table-column label="身高" width="100"><template #default="{ row }">{{ row.height_cm ? `${row.height_cm} cm` : '—' }}</template></el-table-column>
        <el-table-column prop="parent_phone" label="家长电话" min-width="150" />
      </el-table>
      <div class="pagination"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredStudents.length" layout="prev, pager, next, total" /></div>
    </div>
    <el-dialog v-model="dialogVisible" title="新增学生档案" width="500px">
      <el-form label-position="top" @submit.prevent="createStudent">
        <div class="form-grid">
          <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="学号"><el-input v-model="form.student_no" /></el-form-item>
          <el-form-item label="性别"><el-select v-model="form.gender" style="width:100%"><el-option label="男" value="male" /><el-option label="女" value="female" /></el-select></el-form-item>
          <el-form-item label="行政班（可稍后分配）"><el-select v-model="form.class_id" clearable placeholder="暂不分班" style="width:100%"><el-option v-for="item in classes" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="身高（厘米）"><el-input-number v-model="form.height_cm" :min="80" :max="250" :precision="1" :step="0.5" placeholder="例如 172.5" style="width:100%" /></el-form-item>
          <el-form-item label="家长电话" class="wide"><el-input v-model="form.parent_phone" /></el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="createStudent">保存</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.students-page{min-height:100%;padding:32px 38px;background:var(--surface-0)}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}.eyebrow{font-size:11px;color:var(--ink-400);letter-spacing:.8px}h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-header p{margin:0;color:var(--ink-500);font-size:13px}.summary{display:flex;gap:26px;margin-top:22px;color:var(--ink-500);font-size:12px}.summary strong{margin-left:5px;color:var(--ink-950);font-size:18px}.toolbar{display:grid;grid-template-columns:minmax(220px,1fr) 210px 150px auto auto;align-items:end;gap:12px;margin:16px 0 14px;padding:14px;border:1px solid var(--line);background:var(--surface-1)}.filter-field{display:flex;min-width:0;flex-direction:column;gap:6px}.filter-field>span{color:var(--ink-500);font-size:12px}.reset-filter{margin-bottom:1px}.count{align-self:center;color:var(--ink-500);font-size:12px;white-space:nowrap}.table-shell{overflow:hidden;border:1px solid var(--line);border-radius:var(--radius-control);background:var(--surface-1)}.pagination{display:flex;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--line)}.pending{color:var(--amber-500);font-weight:600}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.wide{grid-column:1/-1}@media(max-width:980px){.toolbar{grid-template-columns:1fr 1fr}.count{justify-self:end}}@media(max-width:760px){.students-page{padding:24px 18px}.page-header{align-items:flex-start;flex-direction:column}.toolbar,.form-grid{grid-template-columns:1fr}.count{justify-self:start}.wide{grid-column:auto}}
</style>
