<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi } from '@zhiheng/api'

type GaokaoMode = '3+1+2' | '3+3' | 'traditional'
const provinces = ['北京','天津','河北','山西','内蒙古','辽宁','吉林','黑龙江','上海','江苏','浙江','安徽','福建','江西','山东','河南','湖北','湖南','广东','广西','海南','重庆','四川','贵州','云南','西藏','陕西','甘肃','青海','宁夏','新疆']
const modes: Array<{ value: GaokaoMode; label: string; note: string }> = [
  { value: '3+1+2', label: '3+1+2', note: '物理/历史首选一门，其余四科再选两门' },
  { value: '3+3', label: '3+3', note: '语数外以外，从配置的选考科目中选择三门' },
  { value: 'traditional', label: '传统文理', note: '按文科、理科组织行政班教学' },
]
const form = reactive({ code: '', name: '', province: '', gaokao_mode: '3+1+2' as GaokaoMode })
const loading = ref(false)

async function save() {
  loading.value = true
  try {
    const data = await authApi.updateSchool({ province: form.province, gaokao_mode: form.gaokao_mode })
    Object.assign(form, data)
    ElMessage.success('学校设置已保存，刷新后菜单将按新模式更新')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => Object.assign(form, await authApi.school()))
</script>

<template>
  <section class="settings-page">
    <header><span class="eyebrow">SCHOOL POLICY</span><h1>系统设置</h1><p>配置学校默认高考模式；已建立的届别方案保持原配置，可在选科管理中单独修改。</p></header>
    <el-card shadow="never" class="settings-panel">
      <el-form label-position="top" @submit.prevent="save">
        <div class="identity"><div><span>学校</span><strong>{{ form.name }}</strong></div><div><span>学校代码</span><strong>{{ form.code }}</strong></div></div>
        <el-form-item label="学校所在省份"><el-select v-model="form.province" filterable style="width:100%"><el-option v-for="item in provinces" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="默认高考模式">
          <el-radio-group v-model="form.gaokao_mode" class="mode-list">
            <el-radio v-for="item in modes" :key="item.value" :value="item.value" border><span class="mode-copy"><strong>{{ item.label }}</strong><small>{{ item.note }}</small></span></el-radio>
          </el-radio-group>
        </el-form-item>
        <div class="actions"><el-button type="primary" native-type="submit" :loading="loading">保存设置</el-button></div>
      </el-form>
    </el-card>
  </section>
</template>

<style scoped>
.settings-page{min-height:100%;padding:32px 38px;background:var(--surface-0)}.eyebrow{font-size:11px;color:var(--ink-400);letter-spacing:.8px}h1{margin:7px 0 6px;color:var(--ink-950);font-size:28px}header p{margin:0;color:var(--ink-500);font-size:13px}.settings-panel{max-width:720px;margin-top:24px;border:1px solid var(--line);border-radius:9px}.identity{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;padding-bottom:18px;border-bottom:1px solid var(--line)}.identity span,.mode-copy small{display:block;color:var(--ink-500);font-size:12px}.identity strong{display:block;margin-top:5px;color:var(--ink-950)}.mode-list{display:grid;width:100%;gap:10px}.mode-list :deep(.el-radio){width:100%;height:auto;margin:0;padding:13px 14px}.mode-copy{display:block}.mode-copy strong{display:block;margin-bottom:3px;color:var(--ink-950)}.actions{display:flex;justify-content:flex-end;margin-top:22px}@media(max-width:700px){.settings-page{padding:24px 18px}.identity{grid-template-columns:1fr}}
</style>
