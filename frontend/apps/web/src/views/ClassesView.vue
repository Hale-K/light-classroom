<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { orgApi, schedulingApi, staffApi } from '@zhiheng/api'
import type { ClassInfo, Grade, SchedulingResources, StaffAccount, Student } from '@zhiheng/shared'

const grades = ref<Grade[]>([])
const classes = ref<ClassInfo[]>([])
const students = ref<Student[]>([])
const staffAccounts = ref<StaffAccount[]>([])
const schedulingResources = ref<SchedulingResources>({ teachers: [], subjects: [], classes: [], assignments: [] })
const today = new Date()
const schoolYearStart = today.getMonth() >= 7 ? today.getFullYear() : today.getFullYear() - 1
const academicYear = ref(`${schoolYearStart}-${schoolYearStart + 1}`)
const term = ref('1')
const gradeId = ref<number>()
const selectedClassId = ref<number>()
const classKeyword = ref('')
const rosterKeyword = ref('')
const rosterGender = ref<'male' | 'female' | ''>('')
const rosterPage = ref(1)
const rosterPageSize = 10
const selectedStudentIds = ref<number[]>([])
const candidateKeyword = ref('')
const candidatePage = ref(1)
const candidatePageSize = 10
const loading = ref(false)
const assigning = ref(false)
const assignDialog = ref(false)
const classDialog = ref(false)
const headTeacherDialog = ref(false)
const savingHeadTeacher = ref(false)
const headTeacherId = ref<number>()
const classForm = reactive({ name: '' })
const selectedClass = computed(() => classes.value.find(item => item.id === selectedClassId.value))
const classStudents = computed(() => students.value.filter(item => item.class_id === selectedClassId.value))
const filteredClasses = computed(() => {
  const query = classKeyword.value.trim().toLowerCase()
  return query ? classes.value.filter(item => item.name.toLowerCase().includes(query)) : classes.value
})
const filteredClassStudents = computed(() => {
  const query = rosterKeyword.value.trim().toLowerCase()
  return classStudents.value.filter(item => {
    const matchesKeyword = !query || item.name.toLowerCase().includes(query) || item.student_no?.toLowerCase().includes(query)
    const matchesGender = !rosterGender.value || item.gender === rosterGender.value
    return matchesKeyword && matchesGender
  })
})
const pagedClassStudents = computed(() => filteredClassStudents.value.slice(
  (rosterPage.value - 1) * rosterPageSize,
  rosterPage.value * rosterPageSize,
))
const assignmentCandidates = computed(() => {
  const query = candidateKeyword.value.trim().toLowerCase()
  return students.value.filter(item => item.class_id !== selectedClassId.value
    && (!query || item.name.toLowerCase().includes(query) || item.student_no?.toLowerCase().includes(query)))
})
const pagedCandidates = computed(() => assignmentCandidates.value.slice(
  (candidatePage.value - 1) * candidatePageSize,
  candidatePage.value * candidatePageSize,
))
const unassignedCount = computed(() => students.value.filter(item => !item.class_id).length)
const headTeacherCandidates = computed(() => staffAccounts.value
  .filter(item => item.status === 'active'
    && item.roles.includes('head_teacher')
    && item.roles.includes('subject_teacher'))
  .map(account => {
    const assignments = schedulingResources.value.assignments.filter(item =>
      item.teacher_id === account.id
      && item.academic_year === academicYear.value
      && item.term === term.value)
    const ownAssignment = assignments.find(item => item.class_id === selectedClassId.value)
    return {
      id: account.id,
      name: account.name,
      eligible: Boolean(ownAssignment),
      subjectName: ownAssignment?.subject_name || '未配置本班任教关系',
      taughtClassCount: new Set(assignments.map(item => item.class_id)).size,
    }
  })
  .sort((a, b) => Number(b.eligible) - Number(a.eligible) || a.name.localeCompare(b.name)))

watch([selectedClassId, rosterKeyword, rosterGender], () => { rosterPage.value = 1 })

function resetRosterFilters() {
  rosterKeyword.value = ''
  rosterGender.value = ''
}

async function loadData() {
  loading.value = true
  try {
    const [gradeRows, staffDirectory, resourceRows] = await Promise.all([
      orgApi.grades(), staffApi.list(), schedulingApi.resources(),
    ])
    grades.value = gradeRows
    staffAccounts.value = staffDirectory.accounts
    schedulingResources.value = resourceRows
    gradeId.value ||= grades.value[0]?.id
    ;[classes.value, students.value] = await Promise.all([
      orgApi.classes({ grade_id: gradeId.value, academic_year: academicYear.value, term: term.value }),
      orgApi.students(),
    ])
    if (!classes.value.some(item => item.id === selectedClassId.value)) selectedClassId.value = classes.value[0]?.id
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '班级数据加载失败')
  } finally {
    loading.value = false
  }
}

function openHeadTeacherDialog() {
  if (!selectedClassId.value) return
  headTeacherId.value = selectedClass.value?.head_teacher_id
  headTeacherDialog.value = true
}

async function saveHeadTeacher() {
  if (!selectedClassId.value || !headTeacherId.value) return ElMessage.warning('请选择班主任')
  const candidate = headTeacherCandidates.value.find(item => item.id === headTeacherId.value)
  if (!candidate?.eligible) return ElMessage.warning('请先在排课管理中配置该老师任教本班')
  savingHeadTeacher.value = true
  try {
    await orgApi.assignHeadTeacher(selectedClassId.value, {
      teacher_id: headTeacherId.value,
      academic_year: academicYear.value,
      term: term.value,
    })
    headTeacherDialog.value = false
    ElMessage.success('班主任已配置，并确认其任教本班')
    await loadData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '班主任配置失败')
  } finally {
    savingHeadTeacher.value = false
  }
}

function openAssignment() {
  selectedStudentIds.value = []
  candidateKeyword.value = ''
  candidatePage.value = 1
  assignDialog.value = true
}

async function assignStudents() {
  if (!selectedClassId.value || !selectedStudentIds.value.length) return ElMessage.warning('请选择需要分班的学生')
  assigning.value = true
  try {
    await orgApi.assignStudents(selectedStudentIds.value, selectedClassId.value)
    assignDialog.value = false
    ElMessage.success(`已将 ${selectedStudentIds.value.length} 名学生分入${selectedClass.value?.name}`)
    await loadData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '分班失败')
  } finally {
    assigning.value = false
  }
}

async function removeFromClass(student: Student) {
  try {
    await orgApi.assignStudents([student.id], null)
    ElMessage.success(`${student.name}已移回待分班名单`)
    await loadData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function createClass() {
  if (!gradeId.value || !classForm.name.trim()) return ElMessage.warning('请选择年级并填写班级名称')
  try {
    await orgApi.createClass({ grade_id: gradeId.value, name: classForm.name.trim() })
    classDialog.value = false
    classForm.name = ''
    ElMessage.success('班级已创建')
    await loadData()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '班级创建失败')
  }
}

onMounted(loadData)
</script>

<template>
  <section class="classes-page" v-loading="loading">
    <header class="page-header"><div><span class="eyebrow">ADMINISTRATIVE CLASSES</span><h1>行政班管理</h1><p>学生档案建立后，在这里创建行政班并完成行政分班；新高考教学班由“选科走班”另行生成。</p></div><el-button type="primary" @click="classDialog=true">新建行政班</el-button></header>
    <div class="workspace">
      <aside class="class-list">
        <div class="class-filter"><label><span>学年</span><el-input v-model="academicYear" @change="loadData" /></label><label><span>学期</span><el-select v-model="term" @change="loadData"><el-option label="第一学期" value="1" /><el-option label="第二学期" value="2" /></el-select></label><label><span>年级</span><el-select v-model="gradeId" placeholder="选择年级" @change="loadData"><el-option v-for="grade in grades" :key="grade.id" :label="grade.name" :value="grade.id" /></el-select></label><label><span>班级</span><el-input v-model="classKeyword" clearable placeholder="搜索班级名称" /></label><small>待分班 {{ unassignedCount }} 人</small></div>
        <button v-for="item in filteredClasses" :key="item.id" type="button" class="class-row" :class="{ active: item.id === selectedClassId }" @click="selectedClassId=item.id">
          <span><strong>{{ item.name }}</strong><small>{{ item.head_teacher_name ? `班主任 ${item.head_teacher_name}` : '班主任未配置' }}</small></span><b>{{ item.student_count || 0 }} 人</b>
        </button>
        <div v-if="!filteredClasses.length" class="empty-class">没有符合条件的班级</div>
      </aside>
      <main class="roster">
        <div class="roster-header"><div><h2>{{ selectedClass?.name || '请选择班级' }}</h2><span v-if="selectedClass?.head_teacher_name">班主任 {{ selectedClass.head_teacher_name }} · {{ selectedClass.head_teacher_subject_name }} · 任教 {{ selectedClass.head_teacher_taught_class_count }} 个班</span><span v-else>{{ classStudents.length }} 名学生 · 班主任未配置</span></div><div class="roster-actions"><el-button :disabled="!selectedClassId" @click="openHeadTeacherDialog">配置班主任</el-button><el-button :disabled="!selectedClassId" @click="openAssignment">分配学生</el-button></div></div>
        <div class="roster-toolbar" aria-label="班级学生搜索条件"><label class="filter-field"><span>学生</span><el-input v-model="rosterKeyword" clearable placeholder="姓名或学号" /></label><label class="filter-field"><span>性别</span><el-select v-model="rosterGender" clearable placeholder="全部性别"><el-option label="男" value="male" /><el-option label="女" value="female" /></el-select></label><el-button class="reset-filter" @click="resetRosterFilters">重置</el-button><span class="result-count">当前 {{ filteredClassStudents.length }} 人</span></div>
        <el-table :data="pagedClassStudents" empty-text="该班暂无符合条件的学生">
          <el-table-column prop="student_no" label="学号" min-width="150" /><el-table-column prop="name" label="姓名" min-width="120" /><el-table-column prop="gender" label="性别" width="90" />
          <el-table-column label="操作" width="110" align="right"><template #default="{ row }"><el-button link type="primary" @click="removeFromClass(row)">移出班级</el-button></template></el-table-column>
        </el-table>
        <div class="roster-pagination"><el-pagination v-model:current-page="rosterPage" :page-size="rosterPageSize" :total="filteredClassStudents.length" layout="prev, pager, next, total" /></div>
      </main>
    </div>
    <el-dialog v-model="assignDialog" :title="`分配到${selectedClass?.name || '班级'}`" width="620px">
      <el-input v-model="candidateKeyword" clearable placeholder="搜索姓名或学号" class="candidate-search" @input="candidatePage=1" />
      <el-table :data="pagedCandidates" max-height="420" @selection-change="(rows: Student[]) => selectedStudentIds = rows.map(item => item.id)">
        <el-table-column type="selection" width="48" /><el-table-column prop="student_no" label="学号" min-width="140" /><el-table-column prop="name" label="姓名" min-width="110" /><el-table-column label="当前班级" min-width="140"><template #default="{ row }">{{ row.class_name || '待分班' }}</template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="candidatePage" :page-size="candidatePageSize" :total="assignmentCandidates.length" layout="prev, pager, next, total" class="candidate-pagination" />
      <template #footer><el-button @click="assignDialog=false">取消</el-button><el-button type="primary" :loading="assigning" @click="assignStudents">确认分班</el-button></template>
    </el-dialog>
    <el-dialog v-model="headTeacherDialog" :title="`配置${selectedClass?.name || ''}班主任`" width="520px">
      <p class="dialog-hint">班主任必须同时具有“班主任、任课老师”角色，并已配置任教本班；其学科按实际任教关系识别。</p>
      <el-select v-model="headTeacherId" placeholder="选择任教本班的老师" style="width:100%">
        <el-option v-for="candidate in headTeacherCandidates" :key="candidate.id" :value="candidate.id" :disabled="!candidate.eligible">
          <div class="teacher-option"><strong>{{ candidate.name }}</strong><span>{{ candidate.subjectName }}<template v-if="candidate.eligible"> · 当前任教 {{ candidate.taughtClassCount }} 个班</template></span></div>
        </el-option>
      </el-select>
      <template #footer><el-button @click="headTeacherDialog=false">取消</el-button><el-button type="primary" :loading="savingHeadTeacher" @click="saveHeadTeacher">确认配置</el-button></template>
    </el-dialog>
    <el-dialog v-model="classDialog" title="新建行政班" width="440px"><el-form label-position="top"><el-form-item label="所属年级"><el-select v-model="gradeId" style="width:100%"><el-option v-for="grade in grades" :key="grade.id" :label="grade.name" :value="grade.id" /></el-select></el-form-item><el-form-item label="班级名称"><el-input v-model="classForm.name" placeholder="例如：高一（1）班" /></el-form-item></el-form><template #footer><el-button @click="classDialog=false">取消</el-button><el-button type="primary" @click="createClass">创建</el-button></template></el-dialog>
  </section>
</template>

<style scoped>
.classes-page{min-height:100%;padding:32px 38px;background:var(--surface-0)}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}.eyebrow{font-size:11px;color:var(--ink-400);letter-spacing:.8px}h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-header p{margin:0;color:var(--ink-500);font-size:13px}.workspace{display:grid;grid-template-columns:270px minmax(0,1fr);margin-top:24px;border:1px solid var(--line);border-radius:var(--radius-control);overflow:hidden;background:var(--surface-1)}.class-list{max-height:680px;overflow-y:auto;border-right:1px solid var(--line);padding:12px}.class-filter{display:flex;flex-direction:column;gap:10px;padding:2px 2px 12px}.class-filter label,.filter-field{display:flex;min-width:0;flex-direction:column;gap:6px}.class-filter label>span,.filter-field>span{color:var(--ink-500);font-size:12px}.class-filter small{color:var(--ink-500);font-size:11px}.class-row{display:flex;align-items:center;justify-content:space-between;width:100%;padding:10px;border:0;border-radius:var(--radius-control);background:transparent;color:var(--ink-500);text-align:left;cursor:pointer}.class-row:hover{background:var(--surface-2)}.class-row.active{background:var(--primary-light);color:var(--primary)}.class-row span{display:flex;flex-direction:column;gap:2px}.class-row strong{color:var(--ink-950);font-size:13px}.class-row small{font-size:10px}.class-row b{font-size:12px}.empty-class{padding:28px 8px;text-align:center;color:var(--ink-400);font-size:12px}.roster{min-width:0}.roster-header{height:62px;padding:0 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line)}.roster-header h2{margin:0;color:var(--ink-950);font-size:15px}.roster-header span{color:var(--ink-400);font-size:11px}.roster-actions{display:flex;gap:8px}.roster-toolbar{display:grid;grid-template-columns:minmax(200px,1fr) 140px auto auto;align-items:end;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line);background:var(--surface-0)}.reset-filter{margin-bottom:1px}.result-count{align-self:center;color:var(--ink-500);font-size:12px;white-space:nowrap}.roster-pagination{display:flex;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--line)}.candidate-search{margin-bottom:10px}.candidate-pagination{justify-content:flex-end;margin-top:10px}.dialog-hint{margin:0 0 14px;color:var(--ink-500);font-size:12px;line-height:1.7}.teacher-option{display:flex;align-items:center;justify-content:space-between;gap:16px}.teacher-option span{color:var(--ink-400);font-size:12px}@media(max-width:960px){.roster-toolbar{grid-template-columns:1fr 1fr}.result-count{justify-self:end}}@media(max-width:820px){.classes-page{padding:24px 18px}.workspace{grid-template-columns:1fr}.class-list{max-height:360px;border-right:0;border-bottom:1px solid var(--line)}.page-header{align-items:flex-start;flex-direction:column}}@media(max-width:620px){.roster-toolbar{grid-template-columns:1fr}.result-count{justify-self:start}.roster-actions{gap:4px}}
</style>
