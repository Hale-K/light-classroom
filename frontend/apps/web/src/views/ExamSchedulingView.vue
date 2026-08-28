<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { examApi, examSchedulingApi, orgApi } from '@zhiheng/api'
import type {
  Exam,
  ExamCandidateAssignmentEntry,
  ExamPlan,
  ExamRoomCatalogEntry,
  ExamRoomAssignmentEntry,
  ExamScheduleEntry,
  Grade,
} from '@zhiheng/shared'
import Icon from '@/components/Icon.vue'

const today = new Date()
const localDateValue = (value: Date) => [
  value.getFullYear(),
  String(value.getMonth() + 1).padStart(2, '0'),
  String(value.getDate()).padStart(2, '0'),
].join('-')

const loading = ref(false)
const generating = ref(false)
const savingRooms = ref(false)
const activeSection = ref<'rooms' | 'scheduling'>('rooms')
const exams = ref<Exam[]>([])
const grades = ref<Grade[]>([])
const selectedExamId = ref<number>()
const selectedGradeIds = ref<number[]>([])
const plan = ref<ExamPlan>()
const roomKeyword = ref('')
const roomScope = ref<'all' | 'enabled' | 'disabled'>('all')
const roomPage = ref(1)
const roomPageSize = 10
const confirmedRoomSignature = ref('')
const roomTable = reactive({ keyword: '', date: '', page: 1, pageSize: 10 })
const rooms = ref<Array<{
  id: number
  name: string
  capacity: number
  enabled: boolean
  source_type: 'classroom' | 'custom'
  source_class_id?: number | null
}>>([])
const catalogRows = ref<ExamRoomCatalogEntry[]>([])
const catalogKeyword = ref('')
const catalogPage = ref(1)
const catalogPageSize = 10
const roomEditor = reactive({
  visible: false,
  saving: false,
  id: undefined as number | undefined,
  name: '',
  capacity: 40,
  building: '',
  room_type: 'standard' as 'standard' | 'special' | 'reserve',
})
const form = reactive({
  start_date: localDateValue(today),
  excluded_dates: [] as string[],
  invigilators_per_room: 1,
})

const roster = reactive({
  visible: false,
  loading: false,
  room: null as ExamRoomAssignmentEntry | null,
  keyword: '',
  page: 1,
  pageSize: 10,
  total: 0,
  items: [] as ExamCandidateAssignmentEntry[],
})

const selectedExam = computed(() => exams.value.find(item => item.id === selectedExamId.value))
const filteredCatalogRows = computed(() => {
  const keyword = catalogKeyword.value.trim().toLowerCase()
  return keyword ? catalogRows.value.filter(item => [item.name, item.building]
    .some(value => String(value || '').toLowerCase().includes(keyword))) : catalogRows.value
})
const pagedCatalogRows = computed(() => filteredCatalogRows.value.slice(
  (catalogPage.value - 1) * catalogPageSize,
  catalogPage.value * catalogPageSize,
))
const enabledRooms = computed(() => rooms.value.filter(item => item.enabled))
const enabledRoomCapacity = computed(() => enabledRooms.value.reduce((sum, item) => sum + item.capacity, 0))
const roomSignature = computed(() => JSON.stringify(enabledRooms.value.map(item => [item.id, item.capacity])))
const roomsConfirmed = computed(() => enabledRooms.value.length > 0 && confirmedRoomSignature.value === roomSignature.value)
const filteredRoomConfig = computed(() => {
  const keyword = roomKeyword.value.trim().toLowerCase()
  return rooms.value.filter(item => (
    (roomScope.value === 'all' || (roomScope.value === 'enabled' ? item.enabled : !item.enabled))
    && (!keyword || item.name.toLowerCase().includes(keyword))
  ))
})
const pagedRoomConfig = computed(() => filteredRoomConfig.value.slice(
  (roomPage.value - 1) * roomPageSize,
  roomPage.value * roomPageSize,
))
const roomRows = computed(() => plan.value?.rooms || [])
const roomDates = computed(() => [...new Set(roomRows.value.map(item => item.exam_date))])
const filteredRoomRows = computed(() => {
  const keyword = roomTable.keyword.trim().toLowerCase()
  return roomRows.value.filter(item => (
    (!roomTable.date || item.exam_date === roomTable.date)
    && (!keyword || [item.room_name, item.subject_name, item.grade_name, ...item.invigilator_names]
      .some(value => String(value || '').toLowerCase().includes(keyword)))
  ))
})
const pagedRoomRows = computed(() => filteredRoomRows.value.slice(
  (roomTable.page - 1) * roomTable.pageSize,
  roomTable.page * roomTable.pageSize,
))
const dayGroups = computed(() => {
  const days = new Map<string, Map<number, ExamScheduleEntry[]>>()
  for (const item of plan.value?.schedules || []) {
    const sessions = days.get(item.exam_date) || new Map()
    sessions.set(item.session_index, [...(sessions.get(item.session_index) || []), item])
    days.set(item.exam_date, sessions)
  }
  return [...days.entries()].map(([date, sessions]) => ({
    date,
    sessions: [...sessions.entries()].map(([sessionIndex, items]) => {
      const matchingRooms = roomRows.value.filter(room => room.exam_date === date && room.session_index === sessionIndex)
      return {
        sessionIndex,
        items,
        roomCount: matchingRooms.length,
        candidateCount: matchingRooms.reduce((sum, room) => sum + room.candidate_count, 0),
      }
    }),
  }))
})

function dateLabel(value: string) {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}月${date.getDate()}日 · ${['周日', '周一', '周二', '周三', '周四', '周五', '周六'][date.getDay()]}`
}

function roomTypeLabel(value: ExamRoomCatalogEntry['room_type']) {
  return { standard: '普通考场', special: '特殊考场', reserve: '备用考场' }[value]
}

async function loadPlan() {
  if (!selectedExamId.value) return
  loading.value = true
  try {
    plan.value = await examSchedulingApi.getPlan(selectedExamId.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '排考方案加载失败')
  } finally {
    loading.value = false
  }
}

async function generatePlan() {
  if (!selectedExamId.value) return ElMessage.warning('请先选择考试')
  if (!roomsConfirmed.value) return ElMessage.warning('请先确认本次考试使用的考场')
  generating.value = true
  try {
    plan.value = await examSchedulingApi.generatePlan({
      exam_id: selectedExamId.value,
      grade_ids: selectedGradeIds.value,
      start_date: form.start_date,
      room: '按考场方案分配',
      excluded_dates: form.excluded_dates,
      invigilators_per_room: form.invigilators_per_room,
      sessions: [{ start_time: '09:00', end_time: '11:00' }],
      rooms: enabledRooms.value.map(item => ({ name: item.name, capacity: item.capacity })),
    })
    ElMessage.success(`已为 ${plan.value.summary.student_count} 名考生生成完整排考方案`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '人员排考生成失败')
  } finally {
    generating.value = false
  }
}

async function confirmRooms() {
  if (!selectedExamId.value) return ElMessage.warning('请先选择考试')
  if (!enabledRooms.value.length) return ElMessage.warning('请至少选择一个考场')
  savingRooms.value = true
  try {
    await examSchedulingApi.saveVenues(selectedExamId.value, enabledRooms.value.map(item => ({
      name: item.name,
      capacity: item.capacity,
      source_type: item.source_type,
      source_class_id: item.source_class_id,
    })))
    confirmedRoomSignature.value = roomSignature.value
    ElMessage.success(`已保存并确认 ${enabledRooms.value.length} 间考场，共 ${enabledRoomCapacity.value} 个座位`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '考场保存失败')
  } finally {
    savingRooms.value = false
  }
}

function setAllRooms(enabled: boolean) {
  for (const room of filteredRoomConfig.value) room.enabled = enabled
  roomPage.value = 1
}

async function loadRoomCatalog() {
  const result = await examSchedulingApi.rooms({ page: 1, page_size: 300 })
  catalogRows.value = result.items
  rooms.value = result.items.map(item => ({
    id: item.id,
    name: item.name,
    capacity: item.capacity,
    enabled: true,
    source_type: item.source_class_id ? 'classroom' : 'custom',
    source_class_id: item.source_class_id,
  }))
}

function openRoomEditor(room?: ExamRoomCatalogEntry) {
  roomEditor.id = room?.id
  roomEditor.name = room?.name || ''
  roomEditor.capacity = room?.capacity || 40
  roomEditor.building = room?.building || ''
  roomEditor.room_type = room?.room_type || 'standard'
  roomEditor.visible = true
}

async function saveCatalogRoom() {
  if (!roomEditor.name.trim()) return ElMessage.warning('请输入考场名称')
  roomEditor.saving = true
  try {
    const data = {
      name: roomEditor.name.trim(),
      capacity: roomEditor.capacity,
      building: roomEditor.building.trim(),
      room_type: roomEditor.room_type,
    }
    if (roomEditor.id) await examSchedulingApi.updateRoom(roomEditor.id, data)
    else await examSchedulingApi.createRoom(data)
    roomEditor.visible = false
    await loadRoomCatalog()
    if (selectedExamId.value) await loadVenues()
    ElMessage.success(roomEditor.id ? '考场已修改' : '考场已创建')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '考场保存失败')
  } finally {
    roomEditor.saving = false
  }
}

async function deleteCatalogRoom(room: ExamRoomCatalogEntry) {
  await ElMessageBox.confirm(`删除考场“${room.name}”后，后续排考将不能再选择它。`, '删除考场', {
    type: 'warning',
    confirmButtonText: '确认删除',
    cancelButtonText: '取消',
  })
  await examSchedulingApi.deleteRoom(room.id)
  await loadRoomCatalog()
  if (selectedExamId.value) await loadVenues()
  ElMessage.success('考场已删除')
}

function enterScheduling() {
  activeSection.value = 'scheduling'
  roomPage.value = 1
}

async function loadVenues() {
  if (!selectedExamId.value) return
  try {
    const saved = await examSchedulingApi.venues(selectedExamId.value)
    if (!saved.confirmed) return
    const savedByName = new Map(saved.rooms.map(item => [item.name, item]))
    for (const room of rooms.value) {
      const venue = savedByName.get(room.name)
      room.enabled = Boolean(venue)
      if (venue) room.capacity = venue.capacity
      savedByName.delete(room.name)
    }
    for (const venue of savedByName.values()) {
      rooms.value.push({
        id: venue.id ? -venue.id : -Date.now(),
        name: venue.name,
        capacity: venue.capacity,
        enabled: true,
        source_type: venue.source_type,
        source_class_id: venue.source_class_id,
      })
    }
    confirmedRoomSignature.value = roomSignature.value
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '考场配置加载失败')
  }
}

async function loadExamContext() {
  confirmedRoomSignature.value = ''
  await Promise.all([loadPlan(), loadVenues()])
}

async function loadRoster() {
  if (!selectedExamId.value || !roster.room) return
  roster.loading = true
  try {
    const result = await examSchedulingApi.candidates(selectedExamId.value, {
      room_assignment_id: roster.room.id,
      keyword: roster.keyword,
      page: roster.page,
      page_size: roster.pageSize,
    })
    roster.items = result.items
    roster.total = result.pagination.total
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '考场名单加载失败')
  } finally {
    roster.loading = false
  }
}

function openRoster(room: ExamRoomAssignmentEntry) {
  roster.room = room
  roster.keyword = ''
  roster.page = 1
  roster.visible = true
  loadRoster()
}

function printPage() { window.print() }

watch(selectedExamId, () => {
  loadExamContext()
})
onMounted(async () => {
  const [examRows, gradeRows] = await Promise.all([examApi.list(), orgApi.grades(), loadRoomCatalog()])
  exams.value = examRows
  grades.value = gradeRows
  selectedGradeIds.value = gradeRows.filter(item => item.level === 3).map(item => item.id)
  selectedExamId.value = examRows[0]?.id
})
</script>

<template>
  <main class="exam-plan-page" v-loading="loading">
    <header class="page-head">
      <div>
        <span class="kicker">考试实施 / {{ activeSection === 'rooms' ? '考场管理' : '人员排考' }}</span>
        <h1>排考管理</h1>
        <p>{{ activeSection === 'rooms' ? '先维护学校可用于考试的教室和场地，再进入人员排考。' : '安排科目场次，并落实到每名考生的考场、座位和监考教师。' }}</p>
      </div>
      <div class="head-actions">
        <el-button v-if="activeSection === 'rooms'" type="primary" @click="openRoomEditor()">新建考场</el-button>
        <el-button v-if="activeSection === 'scheduling'" @click="printPage"><Icon name="printer" :size="15" />打印方案</el-button>
        <el-button v-if="activeSection === 'scheduling'" type="primary" :loading="generating" :disabled="!roomsConfirmed" :title="roomsConfirmed ? '' : '请先确认考场'" @click="generatePlan">
          <Icon v-if="!generating" name="clipboard" :size="15" />{{ generating ? '正在排考' : roomsConfirmed ? '生成完整排考' : '请先确认考场' }}
        </el-button>
      </div>
    </header>

    <nav class="module-tabs" aria-label="排考模块切换">
      <button type="button" :class="{ active: activeSection === 'rooms' }" @click="activeSection='rooms'">考场管理<span>创建、修改、删除考场</span></button>
      <button type="button" :class="{ active: activeSection === 'scheduling' }" @click="enterScheduling">人员排考<span>选择考场并安排考生</span></button>
    </nav>

    <section v-if="activeSection === 'rooms'" class="catalog-section" aria-labelledby="catalog-heading">
      <div class="catalog-head">
        <div><span>学校考场资源</span><h2 id="catalog-heading">可用考场清单</h2></div>
        <div class="catalog-stats"><strong>{{ catalogRows.length }}</strong><span>间考场</span><strong>{{ catalogRows.reduce((sum,item)=>sum+item.capacity,0) }}</strong><span>个座位</span></div>
      </div>
      <div class="catalog-tools">
        <el-input v-model="catalogKeyword" clearable placeholder="搜索考场名称或楼栋" @input="catalogPage=1" />
        <el-button type="primary" @click="openRoomEditor()">新建考场</el-button>
      </div>
      <el-table :data="pagedCatalogRows" style="width:100%">
        <el-table-column prop="name" label="考场名称" min-width="240" />
        <el-table-column label="类型" width="120"><template #default="{ row }">{{ roomTypeLabel(row.room_type) }}</template></el-table-column>
        <el-table-column prop="building" label="位置 / 楼栋" min-width="180"><template #default="{ row }">{{ row.building || '未填写' }}</template></el-table-column>
        <el-table-column prop="capacity" label="座位容量" width="120" />
        <el-table-column label="来源" width="130"><template #default="{ row }">{{ row.source_class_id ? '行政班教室' : '手动创建' }}</template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openRoomEditor(row)">修改</el-button><el-button link type="danger" @click="deleteCatalogRoom(row)">删除</el-button></template></el-table-column>
      </el-table>
      <div class="catalog-footer">
        <el-pagination v-model:current-page="catalogPage" :page-size="catalogPageSize" :total="filteredCatalogRows.length" layout="total, prev, pager, next" />
        <el-button type="primary" @click="enterScheduling">进入人员排考</el-button>
      </div>
    </section>

    <section v-if="activeSection === 'scheduling'" class="control-strip" aria-label="排考条件">
      <label>考试<el-select v-model="selectedExamId" placeholder="选择考试"><el-option v-for="item in exams" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
      <label>参考年级<el-select v-model="selectedGradeIds" multiple collapse-tags placeholder="选择年级"><el-option v-for="item in grades" :key="item.id" :label="item.name" :value="item.id" /></el-select></label>
      <label>开考日期<el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" format="YYYY年MM月DD日" /></label>
      <label>排除日期<el-date-picker v-model="form.excluded_dates" type="dates" value-format="YYYY-MM-DD" format="MM月DD日" placeholder="校庆、调休等" /></label>
      <label>每场监考<el-input-number v-model="form.invigilators_per_room" :min="1" :max="3" /></label>
    </section>

    <section v-if="activeSection === 'scheduling'" class="venue-section" aria-labelledby="venue-heading">
      <header class="venue-head">
        <div>
          <span class="venue-kicker">排考前置条件</span>
          <h2 id="venue-heading">确认本次考试使用哪些考场</h2>
          <p>候选项来自“考场管理”。选择本次考试使用的考场并确认后，才能安排考生。</p>
        </div>
        <div class="venue-summary">
          <div><span>已选择</span><strong>{{ enabledRooms.length }} 间</strong></div>
          <div><span>可用座位</span><strong>{{ enabledRoomCapacity }} 个</strong></div>
          <el-tag :type="roomsConfirmed ? 'success' : 'warning'" effect="plain">{{ roomsConfirmed ? '考场已确认' : '等待确认' }}</el-tag>
        </div>
      </header>
      <div class="venue-tools">
        <el-input v-model="roomKeyword" clearable placeholder="搜索候选教室" @input="roomPage=1" />
        <el-radio-group v-model="roomScope" @change="roomPage=1">
          <el-radio-button value="all">全部候选</el-radio-button>
          <el-radio-button value="enabled">已选考场</el-radio-button>
          <el-radio-button value="disabled">未选教室</el-radio-button>
        </el-radio-group>
        <el-button @click="setAllRooms(true)">全部启用</el-button>
        <el-button @click="setAllRooms(false)">全部停用</el-button>
        <span class="venue-change-note" v-if="confirmedRoomSignature && !roomsConfirmed">考场已变更，请重新确认</span>
        <el-button type="primary" :loading="savingRooms" @click="confirmRooms">保存并确认考场</el-button>
      </div>
      <el-table :data="pagedRoomConfig" style="width:100%">
        <el-table-column label="本次使用" width="110"><template #default="{ row }"><el-checkbox v-model="row.enabled">启用</el-checkbox></template></el-table-column>
        <el-table-column prop="name" label="考场名称" min-width="260" />
        <el-table-column label="座位容量" width="190"><template #default="{ row }"><el-input-number v-model="row.capacity" :min="1" :max="500" :disabled="!row.enabled" /></template></el-table-column>
        <el-table-column label="状态" width="120"><template #default="{ row }"><span :class="['venue-status', row.enabled ? 'is-enabled' : '']">{{ row.enabled ? '纳入本次考试' : '本次不使用' }}</span></template></el-table-column>
      </el-table>
      <el-pagination class="venue-pagination" v-model:current-page="roomPage" :page-size="roomPageSize" :total="filteredRoomConfig.length" layout="total, prev, pager, next" />
    </section>

    <section v-if="activeSection === 'scheduling' && plan" class="summary-band" aria-label="排考摘要">
      <div><span>高考模式</span><strong>{{ plan.mode }}</strong></div>
      <div><span>考试天数</span><strong>{{ plan.summary.day_count }}</strong></div>
      <div><span>科目场次</span><strong>{{ plan.summary.session_count }}</strong></div>
      <div><span>参考学生</span><strong>{{ plan.summary.student_count }}</strong></div>
      <div><span>考生任务</span><strong>{{ plan.summary.candidate_assignment_count }}</strong></div>
      <div><span>考场任务</span><strong>{{ plan.summary.room_count }}</strong></div>
      <div><span>监考教师</span><strong>{{ plan.summary.invigilator_count }}</strong></div>
    </section>

    <section v-if="activeSection === 'scheduling' && dayGroups.length" class="timeline-section">
      <div class="section-heading"><div><span>科目日程</span><h2>{{ selectedExam?.name }}</h2></div><em>同一场次内，不冲突的选考科目并行</em></div>
      <div class="day-grid">
        <article v-for="day in dayGroups" :key="day.date" class="day-panel">
          <header><strong>{{ dateLabel(day.date) }}</strong><span>{{ day.sessions.length }} 个场次</span></header>
          <div class="session-list">
            <div v-for="session in day.sessions" :key="session.sessionIndex" class="session-row">
              <time>{{ session.items[0]?.start_time }}—{{ session.items[0]?.end_time }}</time>
              <div><strong>{{ [...new Set(session.items.map(item => item.subject_name))].join(' / ') }}</strong><span>{{ session.roomCount }} 间考场 · {{ session.candidateCount }} 人次</span></div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section v-if="activeSection === 'scheduling' && roomRows.length" class="room-section">
      <div class="section-heading"><div><span>考场执行表</span><h2>人、场、时、科目</h2></div><em>点击“考生名单”查看具体座位</em></div>
      <div class="room-table-tools">
        <el-input v-model="roomTable.keyword" clearable placeholder="搜索考场、科目或监考教师" @input="roomTable.page=1" />
        <el-select v-model="roomTable.date" clearable placeholder="全部日期" @change="roomTable.page=1"><el-option v-for="date in roomDates" :key="date" :label="dateLabel(date)" :value="date" /></el-select>
      </div>
      <el-table :data="pagedRoomRows" style="width:100%">
        <el-table-column label="日期 / 时间" width="190"><template #default="{ row }"><strong>{{ dateLabel(row.exam_date) }}</strong><small class="cell-sub">第 {{ row.session_index }} 场</small></template></el-table-column>
        <el-table-column label="年级 / 科目" min-width="170"><template #default="{ row }"><strong>{{ row.subject_name }}</strong><small class="cell-sub">{{ row.grade_name }}</small></template></el-table-column>
        <el-table-column prop="room_name" label="考场" min-width="150" />
        <el-table-column label="人数 / 容量" width="120"><template #default="{ row }"><span class="seat-count">{{ row.candidate_count }} / {{ row.capacity }}</span></template></el-table-column>
        <el-table-column label="监考教师" min-width="180"><template #default="{ row }">{{ row.invigilator_names.join('、') || '待安排' }}</template></el-table-column>
        <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openRoster(row)">考生名单</el-button></template></el-table-column>
      </el-table>
      <el-pagination class="room-pagination" v-model:current-page="roomTable.page" :page-size="roomTable.pageSize" :total="filteredRoomRows.length" layout="total, prev, pager, next" />
    </section>

    <section v-else-if="activeSection === 'scheduling'" class="empty-state" role="status">
      <Icon name="clipboard" :size="34" />
      <strong>还没有人员排考方案</strong>
      <span>配置开考日期和考场资源后，系统会按高考模式安排每名学生。</span>
    </section>

    <el-dialog v-model="roomEditor.visible" :title="roomEditor.id ? '修改考场' : '新建考场'" width="min(500px, 92vw)">
      <el-form label-position="top" @submit.prevent="saveCatalogRoom">
        <el-form-item label="考场名称" required><el-input v-model="roomEditor.name" maxlength="100" placeholder="例如：第一阶梯教室" /></el-form-item>
        <div class="room-form-grid">
          <el-form-item label="座位容量" required><el-input-number v-model="roomEditor.capacity" :min="1" :max="500" /></el-form-item>
          <el-form-item label="考场类型"><el-select v-model="roomEditor.room_type"><el-option label="普通考场" value="standard" /><el-option label="特殊考场" value="special" /><el-option label="备用考场" value="reserve" /></el-select></el-form-item>
        </div>
        <el-form-item label="位置 / 楼栋"><el-input v-model="roomEditor.building" maxlength="100" placeholder="例如：实验楼 3 层" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="roomEditor.visible=false">取消</el-button><el-button type="primary" :loading="roomEditor.saving" @click="saveCatalogRoom">{{ roomEditor.id ? '保存修改' : '创建考场' }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="roster.visible" :title="`${roster.room?.room_name || ''} · 考生座位表`" size="min(720px, 94vw)">
      <div class="roster-meta" v-if="roster.room"><div><span>科目</span><strong>{{ roster.room.subject_name }}</strong></div><div><span>年级</span><strong>{{ roster.room.grade_name }}</strong></div><div><span>人数</span><strong>{{ roster.room.candidate_count }}</strong></div><div><span>监考</span><strong>{{ roster.room.invigilator_names.join('、') }}</strong></div></div>
      <div class="roster-search"><el-input v-model="roster.keyword" clearable placeholder="搜索姓名或学号" @keyup.enter="roster.page=1;loadRoster()" /><el-button @click="roster.page=1;loadRoster()">查询</el-button></div>
      <el-table v-loading="roster.loading" :data="roster.items" style="width:100%">
        <el-table-column prop="seat_no" label="座位号" width="80" align="center" />
        <el-table-column prop="student_no" label="学号" min-width="130" />
        <el-table-column prop="student_name" label="姓名" min-width="110" />
        <el-table-column prop="subject_name" label="科目" width="90" />
      </el-table>
      <el-pagination class="roster-pagination" v-model:current-page="roster.page" :page-size="roster.pageSize" :total="roster.total" layout="total, prev, pager, next" @current-change="loadRoster" />
    </el-drawer>
  </main>
</template>

<style scoped>
.exam-plan-page{max-width:1480px;margin:0 auto;padding:30px 34px 48px}.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:22px}.kicker{color:var(--blue-600);font-size:11px;font-weight:700}.page-head h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-head p{margin:0;color:var(--ink-500);font-size:13px}.head-actions{display:flex;gap:8px}.head-actions :deep(.el-button span){display:flex;align-items:center;gap:6px}.control-strip{display:grid;grid-template-columns:1.3fr 150px 170px 1fr 110px 140px;gap:12px;padding:16px;border:1px solid var(--line);background:#fff}.control-strip>label{display:flex;min-width:0;flex-direction:column;gap:6px;color:var(--ink-500);font-size:10px}.control-strip :deep(.el-select),.control-strip :deep(.el-date-editor),.control-strip :deep(.el-input-number){width:100%}.room-resource{display:flex;min-width:0;flex-direction:column;justify-content:center;align-items:flex-start;padding:8px 12px;border:1px solid var(--line);background:var(--surface-0);color:var(--ink-500);cursor:pointer}.room-resource strong{margin-top:2px;color:var(--ink-950);font-size:18px}.room-resource small{font-size:9px}.summary-band{display:grid;grid-template-columns:repeat(7,1fr);margin-top:14px;border:1px solid var(--line);background:#fff}.summary-band div{padding:13px 15px;border-right:1px solid var(--line)}.summary-band div:last-child{border-right:0}.summary-band span,.summary-band strong{display:block}.summary-band span{color:var(--ink-500);font-size:9px}.summary-band strong{margin-top:5px;color:var(--ink-950);font-size:20px;font-variant-numeric:tabular-nums}.timeline-section,.room-section{margin-top:26px}.section-heading{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:12px}.section-heading span{color:var(--blue-600);font-size:9px;font-weight:700}.section-heading h2{margin:4px 0 0;color:var(--ink-950);font-size:17px}.section-heading em{color:var(--ink-500);font-size:10px;font-style:normal}.day-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}.day-panel{border:1px solid var(--line);background:#fff}.day-panel>header{display:flex;align-items:center;justify-content:space-between;padding:13px 15px;border-top:3px solid var(--graphite-950);border-bottom:1px solid var(--line)}.day-panel>header strong{font-size:13px}.day-panel>header span{color:var(--ink-500);font-size:9px}.session-list{padding:6px 15px}.session-row{display:grid;grid-template-columns:108px 1fr;align-items:center;gap:12px;padding:13px 0;border-bottom:1px solid var(--line)}.session-row:last-child{border-bottom:0}.session-row time{color:var(--blue-600);font-size:10px;font-variant-numeric:tabular-nums}.session-row strong,.session-row span{display:block}.session-row strong{color:var(--ink-950);font-size:13px}.session-row span{margin-top:4px;color:var(--ink-500);font-size:9px}.room-section{padding:18px;border:1px solid var(--line);background:#fff}.room-table-tools{display:flex;gap:10px;margin-bottom:12px}.room-table-tools :deep(.el-input){max-width:320px}.room-table-tools :deep(.el-select){width:180px}.room-section :deep(.el-table){border-top:1px solid var(--line)}.room-pagination{justify-content:flex-end;margin-top:14px}.cell-sub{display:block;margin-top:4px;color:var(--ink-500);font-size:9px}.seat-count{font-variant-numeric:tabular-nums}.empty-state{min-height:420px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px solid var(--line);background:#fff;color:var(--ink-500)}.empty-state svg{color:#aab3c0}.empty-state strong{margin-top:12px;color:var(--ink-950);font-size:14px}.empty-state span{margin-top:6px;font-size:11px}.room-config-head,.roster-search{display:flex;align-items:center;gap:10px;margin-bottom:14px}.room-config-head span{margin-left:auto;color:var(--ink-500);font-size:10px}.room-config-head :deep(.el-input){max-width:260px}.roster-meta{display:grid;grid-template-columns:repeat(4,1fr);margin-bottom:14px;border:1px solid var(--line)}.roster-meta div{padding:11px;border-right:1px solid var(--line)}.roster-meta div:last-child{border-right:0}.roster-meta span,.roster-meta strong{display:block}.roster-meta span{color:var(--ink-500);font-size:9px}.roster-meta strong{margin-top:4px;color:var(--ink-950);font-size:12px}.roster-pagination{justify-content:flex-end;margin-top:14px}@media(max-width:1080px){.exam-plan-page{padding:22px 16px}.control-strip{grid-template-columns:repeat(2,1fr)}.summary-band{grid-template-columns:repeat(4,1fr)}.summary-band div{border-bottom:1px solid var(--line)}}@media(max-width:680px){.page-head{align-items:flex-start;flex-direction:column}.control-strip{grid-template-columns:1fr}.summary-band{grid-template-columns:repeat(2,1fr)}.day-grid{grid-template-columns:1fr}.room-table-tools{align-items:stretch;flex-direction:column}.room-table-tools :deep(.el-input),.room-table-tools :deep(.el-select){max-width:none;width:100%}.roster-meta{grid-template-columns:repeat(2,1fr)}}@media print{.page-head,.control-strip,.room-config-head,.room-table-tools,.room-pagination{display:none}.exam-plan-page{padding:0}.room-section{border:0;padding:0}}
.control-strip{grid-template-columns:1.3fr 150px 170px 1fr 110px}.venue-section{margin-top:14px;border:1px solid var(--line);background:#fff}.venue-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:18px;border-bottom:1px solid var(--line)}.venue-kicker{color:var(--blue-600);font-size:9px;font-weight:700}.venue-head h2{margin:4px 0 5px;color:var(--ink-950);font-size:17px}.venue-head p{margin:0;color:var(--ink-500);font-size:10px}.venue-summary{display:flex;align-items:center;gap:22px}.venue-summary div{min-width:76px}.venue-summary span,.venue-summary strong{display:block}.venue-summary span{color:var(--ink-500);font-size:9px}.venue-summary strong{margin-top:4px;color:var(--ink-950);font-size:16px}.venue-tools{display:flex;align-items:center;gap:8px;padding:12px 18px}.venue-tools :deep(.el-input){max-width:280px}.venue-tools>.el-button:last-child{margin-left:auto}.venue-change-note{margin-left:auto;color:var(--el-color-warning);font-size:10px}.venue-change-note+.el-button{margin-left:0!important}.venue-pagination{justify-content:flex-end;padding:12px 18px;border-top:1px solid var(--line)}.venue-status{color:var(--ink-400);font-size:10px}.venue-status.is-enabled{color:var(--blue-600);font-weight:600}@media(max-width:1080px){.venue-head{align-items:flex-start;flex-direction:column}.venue-summary{width:100%}}@media(max-width:680px){.venue-tools{align-items:stretch;flex-wrap:wrap}.venue-tools :deep(.el-input){max-width:none;width:100%}.venue-tools>.el-button:last-child,.venue-change-note{margin-left:0}.venue-summary{align-items:flex-start;flex-wrap:wrap}}
@media(max-width:1080px){.control-strip{grid-template-columns:repeat(2,1fr)}}@media(max-width:680px){.control-strip{grid-template-columns:1fr}}
.module-tabs{display:flex;margin-bottom:14px;border-bottom:1px solid var(--line)}.module-tabs button{position:relative;min-width:210px;padding:13px 16px;border:0;background:transparent;color:var(--ink-500);text-align:left;cursor:pointer}.module-tabs button::after{position:absolute;right:0;bottom:-1px;left:0;height:2px;background:transparent;content:""}.module-tabs button.active{color:var(--ink-950)}.module-tabs button.active::after{background:var(--blue-600)}.module-tabs button>span{display:block;margin-top:3px;color:var(--ink-400);font-size:9px}.catalog-section{border:1px solid var(--line);background:#fff}.catalog-head{display:flex;align-items:flex-end;justify-content:space-between;padding:18px;border-bottom:1px solid var(--line)}.catalog-head>div:first-child span{color:var(--blue-600);font-size:9px;font-weight:700}.catalog-head h2{margin:4px 0 0;color:var(--ink-950);font-size:18px}.catalog-stats{display:grid;grid-template-columns:auto auto auto auto;align-items:baseline;gap:5px 8px}.catalog-stats strong{color:var(--ink-950);font-size:20px}.catalog-stats span{color:var(--ink-500);font-size:9px}.catalog-tools{display:flex;gap:8px;padding:12px 18px}.catalog-tools :deep(.el-input){max-width:320px}.catalog-tools .el-button{margin-left:auto}.catalog-footer{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-top:1px solid var(--line)}.room-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.room-form-grid :deep(.el-input-number),.room-form-grid :deep(.el-select){width:100%}@media(max-width:680px){.module-tabs button{min-width:0;flex:1}.catalog-head{align-items:flex-start;flex-direction:column;gap:12px}.catalog-footer{align-items:stretch;flex-direction:column;gap:12px}.room-form-grid{grid-template-columns:1fr}}
</style>
