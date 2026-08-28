<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { staffApi } from '@zhiheng/api'
import type { StaffAccount, StaffRoleCode, StaffRoleOption } from '@zhiheng/shared'

const accounts = ref<StaffAccount[]>([])
const roleOptions = ref<StaffRoleOption[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editing = ref<StaffAccount>()
const keyword = ref('')
const roleFilter = ref<StaffRoleCode | ''>('')
const statusFilter = ref<'active' | 'disabled' | ''>('')
const page = ref(1)
const pageSize = 10
const form = reactive({ name: '', phone: '', password: '', roles: [] as StaffRoleCode[] })
const roleNames: Record<string, string> = {
  school_admin: '校长管理员',
  head_teacher: '班主任',
  subject_teacher: '任教老师',
  academic_director: '教导主任',
}
const filteredAccounts = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return accounts.value.filter(item => {
    const matchesKeyword = !query || item.name.toLowerCase().includes(query) || item.phone.includes(query)
    const matchesRole = !roleFilter.value || item.roles.includes(roleFilter.value)
    const matchesStatus = !statusFilter.value || item.status === statusFilter.value
    return matchesKeyword && matchesRole && matchesStatus
  })
})
const pagedAccounts = computed(() => filteredAccounts.value.slice(
  (page.value - 1) * pageSize,
  page.value * pageSize,
))

watch([keyword, roleFilter, statusFilter], () => { page.value = 1 })

function resetFilters() {
  keyword.value = ''
  roleFilter.value = ''
  statusFilter.value = ''
}

async function loadStaff() {
  loading.value = true
  try {
    const data = await staffApi.list()
    accounts.value = data.accounts
    roleOptions.value = data.roles
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '人员信息加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = undefined
  Object.assign(form, { name: '', phone: '', password: '', roles: ['subject_teacher'] })
  dialogVisible.value = true
}

function openRoles(account: StaffAccount) {
  editing.value = account
  Object.assign(form, {
    name: account.name,
    phone: account.phone,
    password: '',
    roles: account.roles.filter(role => role !== 'school_admin') as StaffRoleCode[],
  })
  dialogVisible.value = true
}

async function submit() {
  if (!form.roles.length) {
    ElMessage.warning('请至少分配一个角色')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await staffApi.updateRoles(editing.value.id, form.roles)
      ElMessage.success('角色分配已更新')
    } else {
      await staffApi.create({
        name: form.name.trim(),
        phone: form.phone.trim(),
        password: form.password,
        roles: form.roles,
      })
      ElMessage.success('教职工账号已创建')
    }
    dialogVisible.value = false
    await loadStaff()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleStatus(account: StaffAccount, active: string | number | boolean) {
  const previous = account.status
  account.status = active ? 'active' : 'disabled'
  try {
    await staffApi.updateStatus(account.id, account.status)
    ElMessage.success(account.status === 'active' ? '账号已启用' : '账号已停用')
  } catch (error) {
    account.status = previous
    ElMessage.error(error instanceof Error ? error.message : '账号状态更新失败')
  }
}

onMounted(loadStaff)
</script>

<template>
  <section class="staff-page">
    <header class="page-header">
      <div>
        <span class="eyebrow">PEOPLE & ACCESS</span>
        <h1>人员与权限</h1>
        <p>校长管理本校登录账号；班主任、任教老师和教导主任可按实际职责组合分配。</p>
      </div>
      <el-button type="primary" @click="openCreate">新增教职工</el-button>
    </header>

    <div class="role-note">
      <strong>权限原则</strong>
      <span>校长管理员不可降权；教职工可同时承担多个角色，教导主任拥有排课、选科分班和排考管理权限。</span>
    </div>

    <div class="staff-toolbar" aria-label="人员搜索条件">
      <label class="filter-field"><span>人员</span><el-input v-model="keyword" clearable placeholder="姓名或手机号" /></label>
      <label class="filter-field"><span>角色</span><el-select v-model="roleFilter" clearable placeholder="全部角色"><el-option v-for="role in roleOptions" :key="role.code" :label="role.name" :value="role.code" /></el-select></label>
      <label class="filter-field"><span>状态</span><el-select v-model="statusFilter" clearable placeholder="全部状态"><el-option label="启用" value="active" /><el-option label="停用" value="disabled" /></el-select></label>
      <el-button class="reset-filter" @click="resetFilters">重置</el-button>
      <span class="result-count">共 {{ filteredAccounts.length }} 个账号</span>
    </div>

    <div class="staff-table" v-loading="loading">
      <el-table :data="pagedAccounts" empty-text="暂无教职工账号">
        <el-table-column label="人员" min-width="170">
          <template #default="{ row }">
            <div class="person"><strong>{{ row.name }}</strong><span>{{ row.phone }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="330">
          <template #default="{ row }">
            <div class="role-tags">
              <el-tag v-for="role in row.roles" :key="role" effect="plain" :type="role === 'school_admin' ? 'primary' : 'info'">
                {{ roleNames[role] || role }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="账号状态" width="130">
          <template #default="{ row }">
            <el-switch
              :model-value="row.status === 'active'"
              :disabled="row.is_school_admin"
              inline-prompt
              active-text="启用"
              inactive-text="停用"
              @change="(value: string | number | boolean) => toggleStatus(row, value)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.is_school_admin" class="locked">校长账号</span>
            <el-button v-else link type="primary" @click="openRoles(row)">分配角色</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredAccounts.length" layout="prev, pager, next, total" />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '分配人员角色' : '新增教职工账号'" width="520px">
      <el-form label-position="top" @submit.prevent="submit">
        <div v-if="!editing" class="account-fields">
          <el-form-item label="姓名"><el-input v-model="form.name" maxlength="50" /></el-form-item>
          <el-form-item label="登录手机号"><el-input v-model="form.phone" maxlength="20" /></el-form-item>
          <el-form-item label="初始密码"><el-input v-model="form.password" type="password" show-password maxlength="64" /></el-form-item>
        </div>
        <div v-else class="editing-person"><strong>{{ form.name }}</strong><span>{{ form.phone }}</span></div>
        <el-form-item label="人员角色">
          <el-checkbox-group v-model="form.roles" class="role-options">
            <el-checkbox v-for="role in roleOptions" :key="role.code" :label="role.code">
              <span class="role-copy"><strong>{{ role.name }}</strong><small>{{ role.description }}</small></span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.staff-page{min-height:100%;padding:32px 38px;background:var(--surface-0)}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}.eyebrow{font-size:11px;color:var(--ink-400);letter-spacing:.8px}h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}.page-header p{margin:0;color:var(--ink-500);font-size:13px}.role-note{display:flex;align-items:center;gap:14px;margin:24px 0 14px;padding:12px 14px;border-left:3px solid var(--primary);background:var(--primary-light);color:var(--ink-500);font-size:12px}.role-note strong{color:var(--ink-950);white-space:nowrap}.staff-toolbar{display:grid;grid-template-columns:minmax(220px,1fr) 180px 150px auto auto;align-items:end;gap:12px;margin-bottom:14px;padding:14px;border:1px solid var(--line);background:var(--surface-1)}.filter-field{display:flex;min-width:0;flex-direction:column;gap:6px}.filter-field>span{color:var(--ink-500);font-size:12px}.reset-filter{margin-bottom:1px}.result-count{align-self:center;color:var(--ink-500);font-size:12px;white-space:nowrap}.staff-table{overflow:hidden;border:1px solid var(--line);border-radius:var(--radius-control);background:var(--surface-1)}.pagination{display:flex;justify-content:flex-end;padding:10px 14px;border-top:1px solid var(--line)}.person,.editing-person{display:flex;flex-direction:column;gap:3px}.person strong,.editing-person strong{color:var(--ink-950);font-size:13px}.person span,.editing-person span,.locked{color:var(--ink-400);font-size:12px}.role-tags{display:flex;flex-wrap:wrap;gap:6px}.account-fields{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.account-fields .el-form-item:last-child{grid-column:1/-1}.editing-person{margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid var(--line)}.role-options{display:flex;width:100%;flex-direction:column}.role-options :deep(.el-checkbox){height:auto;margin:0;padding:11px 0;border-bottom:1px solid var(--line)}.role-options :deep(.el-checkbox:last-child){border-bottom:0}.role-copy{display:inline-flex;flex-direction:column;gap:2px}.role-copy strong{color:var(--ink-950);font-weight:600}.role-copy small{color:var(--ink-500);font-size:11px}@media(max-width:980px){.staff-toolbar{grid-template-columns:1fr 1fr}.result-count{justify-self:end}}@media(max-width:760px){.staff-page{padding:24px 18px}.page-header{align-items:flex-start;flex-direction:column}.staff-toolbar{grid-template-columns:1fr}.result-count{justify-self:start}.account-fields{grid-template-columns:1fr}}
</style>
