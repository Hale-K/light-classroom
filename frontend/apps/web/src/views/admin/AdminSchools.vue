<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAdminStore } from '@/stores/admin'
import type { AdminSchool } from '@zhiheng/shared'

const admin = useAdminStore()
const loading = ref(false)
const dialogVisible = ref(false)
type GaokaoMode = '3+1+2' | '3+3' | 'traditional'
const gaokaoModeOptions: Array<{ value: GaokaoMode; label: string }> = [
  { value: '3+1+2', label: '新高考 3+1+2' },
  { value: '3+3', label: '新高考 3+3' },
  { value: 'traditional', label: '传统文理高考' },
]
const provinces = [
  '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江', '上海', '江苏',
  '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '广西',
  '海南', '重庆', '四川', '贵州', '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆',
]
const form = reactive({
  code: '', name: '', province: '', gaokao_mode: '3+1+2' as GaokaoMode,
  admin_name: '', admin_phone: '', admin_password: '',
})

// 编辑学校：名称/手机号可改，代码只读
const editVisible = ref(false)
const editing = reactive<{
  id: number; code: string; name: string; province: string
  gaokao_mode: GaokaoMode; admin_phone: string
}>({
  id: 0, code: '', name: '', province: '', gaokao_mode: '3+1+2', admin_phone: '',
})
const savingEdit = ref(false)

function openEdit(row: AdminSchool) {
  Object.assign(editing, {
    id: row.id, code: row.code, name: row.name, province: row.province,
    gaokao_mode: row.gaokao_mode, admin_phone: row.admin_phone || '',
  })
  editVisible.value = true
}

async function saveEdit() {
  if (!editing.name.trim()) {
    ElMessage.warning('学校名称不能为空')
    return
  }
  savingEdit.value = true
  try {
    await admin.updateSchool(editing.id, {
      name: editing.name.trim(),
      province: editing.province,
      gaokao_mode: editing.gaokao_mode,
      admin_phone: editing.admin_phone.trim() || undefined,
    })
    editVisible.value = false
    ElMessage.success('学校信息已更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    savingEdit.value = false
  }
}

// 重置校长登录密码
const resetVisible = ref(false)
const resettingId = ref(0)
const resettingName = ref('')
const resettingPhone = ref('')
const newPassword = ref('')
const savingReset = ref(false)

function openReset(row: AdminSchool) {
  resettingId.value = row.id
  resettingName.value = row.name
  resettingPhone.value = row.admin_phone || ''
  newPassword.value = ''
  resetVisible.value = true
}

async function confirmReset() {
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  savingReset.value = true
  try {
    await admin.resetPassword(resettingId.value, newPassword.value)
    resetVisible.value = false
    ElMessage.success('密码已重置')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重置失败')
  } finally {
    savingReset.value = false
  }
}

async function loadSchools() {
  loading.value = true
  try {
    await admin.loadSchools()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '学校列表加载失败')
  } finally {
    loading.value = false
  }
}

async function createSchool() {
  if (!form.code || !form.name || !form.province || !form.gaokao_mode || !form.admin_name || !form.admin_password) {
    ElMessage.warning('请先填写学校代码、名称和管理员信息')
    return
  }
  try {
    await admin.createSchool(form)
    dialogVisible.value = false
    Object.assign(form, {
      code: '', name: '', province: '', gaokao_mode: '3+1+2',
      admin_name: '', admin_phone: '', admin_password: '',
    })
    ElMessage.success('学校已创建')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建学校失败')
  }
}

onMounted(loadSchools)
</script>

<template>
  <section class="schools-page">
    <div class="page-heading">
      <div>
        <span class="eyebrow">TENANT DIRECTORY</span>
        <h1>学校管理</h1>
        <p>创建和维护接入轻课堂的学校工作区。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">新增学校</el-button>
    </div>

    <div class="summary-card">
      <span class="summary-label">当前学校总数</span>
      <strong>{{ admin.schools.length }}</strong>
      <span class="summary-note">已接入平台的学校工作区</span>
    </div>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="card-header"><strong>学校目录</strong><el-button link @click="loadSchools">刷新</el-button></div>
      </template>
      <el-table v-loading="loading" :data="admin.schools" empty-text="暂时没有学校">
        <el-table-column prop="name" label="学校名称" min-width="220" />
        <el-table-column prop="code" label="学校代码" width="160" />
        <el-table-column prop="province" label="省份" width="110" />
        <el-table-column label="高考模式" width="150">
          <template #default="{ row }">
            {{ gaokaoModeOptions.find(item => item.value === row.gaokao_mode)?.label || row.gaokao_mode }}
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="140" />
        <el-table-column prop="admin_phone" label="管理员电话" min-width="160" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="openReset(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增学校" width="460px">
      <el-form label-position="top" @submit.prevent="createSchool">
        <el-form-item label="学校名称"><el-input v-model="form.name" placeholder="例如：衡川实验中学" /></el-form-item>
        <el-form-item label="学校代码"><el-input v-model="form.code" placeholder="例如：hengchuan" /></el-form-item>
        <el-form-item label="学校所在省份">
          <el-select v-model="form.province" filterable placeholder="请选择省份" style="width: 100%">
            <el-option v-for="item in provinces" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认高考模式">
          <el-radio-group v-model="form.gaokao_mode">
            <el-radio-button v-for="item in gaokaoModeOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </el-radio-button>
          </el-radio-group>
          <div class="code-hint">新建届别方案时继承该模式，之后可按入学年份单独调整。</div>
        </el-form-item>
        <el-form-item label="管理员姓名"><el-input v-model="form.admin_name" /></el-form-item>
        <el-form-item label="管理员电话"><el-input v-model="form.admin_phone" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="form.admin_password" type="password" show-password /></el-form-item>
        <div class="dialog-actions"><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" native-type="submit">创建学校</el-button></div>
      </el-form>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑学校" width="420px">
      <el-form label-position="top" @submit.prevent="saveEdit">
        <el-form-item label="学校名称"><el-input v-model="editing.name" placeholder="请输入学校名称" /></el-form-item>
        <el-form-item label="学校所在省份">
          <el-select v-model="editing.province" filterable style="width: 100%">
            <el-option v-for="item in provinces" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认高考模式">
          <el-select v-model="editing.gaokao_mode" style="width: 100%">
            <el-option v-for="item in gaokaoModeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <div class="code-hint">修改后影响新建届别；已存在的届别方案保持原模式，可单独修改。</div>
        </el-form-item>
        <el-form-item label="管理员手机号">
          <el-input v-model="editing.admin_phone" placeholder="校长登录账号" />
          <div class="code-hint">仅变更校长登录手机号；超管身份与密码保持不变</div>
        </el-form-item>
        <el-form-item label="学校代码">
          <el-input :model-value="editing.code" disabled placeholder="学校代码不可修改" />
          <div class="code-hint">学校代码作为系统标识，创建后不可修改</div>
        </el-form-item>
        <div class="dialog-actions"><el-button @click="editVisible = false">取消</el-button><el-button type="primary" native-type="submit" :loading="savingEdit">保存</el-button></div>
      </el-form>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="400px">
      <el-form label-position="top" @submit.prevent="confirmReset">
        <div class="reset-target">为「{{ resettingName }}」{{ resettingPhone ? `（校长 ${resettingPhone}）` : '' }} 设置新登录密码</div>
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <div class="dialog-actions"><el-button @click="resetVisible = false">取消</el-button><el-button type="primary" native-type="submit" :loading="savingReset">确认重置</el-button></div>
      </el-form>
    </el-dialog>
  </section>
</template>

<style scoped>
.schools-page { min-height: 100%; padding: 34px 38px; background: var(--surface-0); }
.page-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 26px; }
.eyebrow { color: var(--ink-400); font-size: 11px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }
h1 { margin: 8px 0 7px; color: var(--ink-950); font-size: 28px; letter-spacing: -.5px; }
.page-heading p { margin: 0; color: var(--ink-500); font-size: 13px; }
.summary-card { display: flex; align-items: baseline; gap: 14px; width: fit-content; margin-bottom: 18px; padding: 18px 22px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.summary-label, .summary-note { color: var(--ink-500); font-size: 12px; }
.summary-card strong { color: var(--ink-950); font-size: 26px; }
.table-card { border: 1px solid var(--line); border-radius: 10px; }
.card-header { display: flex; align-items: center; justify-content: space-between; color: var(--ink-950); }
.code-hint { margin-top: 6px; color: var(--ink-400); font-size: 12px; line-height: 1.4; }
.reset-target { margin-bottom: 16px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-1); color: var(--ink-700); font-size: 13px; line-height: 1.5; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
@media (max-width: 680px) { .schools-page { padding: 24px 18px; } .page-heading { align-items: flex-start; flex-direction: column; } .summary-card { width: auto; } }
</style>
