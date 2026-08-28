<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import Icon from '@/components/Icon.vue'
import { useAuthStore } from '@/stores/auth'
import { APP_NAME } from '@zhiheng/shared'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ phone: '', password: '' })
const rules: FormRules = { phone: [{ required: true, message: '请输入手机号', trigger: 'blur' }, { pattern: /^1\d{10}$/, message: '手机号格式不正确', trigger: 'blur' }], password: [{ required: true, message: '请输入密码', trigger: 'blur' }] }

async function onSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try { await auth.login(form.phone, form.password); ElMessage.success(`欢迎回来，${auth.displayName || '老师'}`); router.replace((route.query.redirect as string) || '/dashboard') }
    catch (e) { ElMessage.error((e as Error).message || '登录失败，请重试') }
    finally { loading.value = false }
  })
}
</script>

<template>
  <main class="login-page">
    <section class="login-brand">
      <div class="brand-header">
        <div class="brand-mark">衡</div>
        <div>
          <strong>{{ APP_NAME }}</strong>
          <small>轻课堂教务系统</small>
        </div>
      </div>
      <div class="brand-body">
        <h1>扫描、阅卷、分析，<br />一套系统完成。</h1>
        <p>面向普通高中日常考试流程，连接纸质答卷与线上教务管理。</p>
        <div class="brand-features">
          <div class="feature-item">
            <span class="feature-num">01</span>
            <div>
              <b>扫描进卷</b>
              <small>批量切分 · 自动分配</small>
            </div>
          </div>
          <div class="feature-item">
            <span class="feature-num">02</span>
            <div>
              <b>高效打分</b>
              <small>键盘流 · 30 秒/份</small>
            </div>
          </div>
          <div class="feature-item">
            <span class="feature-num">03</span>
            <div>
              <b>学情回流</b>
              <small>诊断 · 巩固 · 再验证</small>
            </div>
          </div>
        </div>
      </div>
      <div class="brand-footer">
        <span>普通高中教务工作台</span>
        <span>校内数据独立管理</span>
      </div>
    </section>

    <section class="login-form-side">
      <div class="login-form-card">
        <div class="form-heading">
          <span class="form-kicker">账号登录</span>
          <h2>登录工作台</h2>
          <p>使用学校分配的账号登录。</p>
        </div>
        <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="onSubmit">
          <el-form-item prop="phone">
            <label for="phone">手机号</label>
            <el-input id="phone" v-model="form.phone" placeholder="请输入手机号" maxlength="11" autofocus>
              <template #prefix><Icon name="users" :size="16" /></template>
            </el-input>
          </el-form-item>
          <el-form-item prop="password">
            <label for="password">密码</label>
            <el-input id="password" v-model="form.password" type="password" placeholder="请输入密码" show-password @keyup.enter="onSubmit">
              <template #prefix><Icon name="keyboard" :size="16" /></template>
            </el-input>
          </el-form-item>
          <button class="submit-button" type="submit" :disabled="loading">
            {{ loading ? '正在进入…' : '进入工作台' }}
            <Icon name="arrow-right" :size="16" />
          </button>
        </el-form>
        <div class="login-note">
          <span><span class="note-dot" />学校数据隔离</span>
          <span><span class="note-dot" />私有化部署</span>
          <span><span class="note-dot" />操作全程留痕</span>
        </div>
      </div>
      <div class="form-footer">{{ APP_NAME }} · 轻课堂 <span>© 2026</span></div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100%;
  display: grid;
  grid-template-columns: minmax(460px, 1.05fr) minmax(420px, 0.95fr);
  background: var(--surface-0);
}

/* 左侧品牌区 */
.login-brand {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  padding: 40px 8%;
  background: var(--surface-1);
  border-right: 1px solid var(--line);
}
.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
}
.brand-header strong {
  display: block;
  font-size: 17px;
  font-weight: 700;
  color: var(--ink-950);
  letter-spacing: 0.5px;
}
.brand-header small {
  display: block;
  margin-top: 2px;
  color: var(--ink-400);
  font-size: 11px;
}
.brand-body {
  max-width: 480px;
  margin: auto 0;
}
.brand-body h1 {
  margin: 0 0 16px;
  color: var(--ink-950);
  font-size: clamp(32px, 4vw, 48px);
  line-height: 1.2;
  font-weight: 700;
  letter-spacing: -1px;
}
.brand-body p {
  max-width: 380px;
  margin: 0;
  color: var(--ink-500);
  font-size: 14px;
  line-height: 1.7;
}
.brand-features {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-top: 48px;
}
.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.feature-num {
  color: var(--ink-400);
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  padding-top: 2px;
  min-width: 24px;
}
.feature-item b {
  display: block;
  color: var(--ink-950);
  font-size: 14px;
  font-weight: 600;
}
.feature-item small {
  display: block;
  margin-top: 3px;
  color: var(--ink-400);
  font-size: 12px;
}
.brand-footer {
  display: flex;
  gap: 24px;
  color: var(--ink-400);
  font-size: 11px;
}

/* 右侧表单区 */
.login-form-side {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 8%;
  position: relative;
}
.login-form-card {
  width: min(100%, 380px);
}
.form-heading {
  margin-bottom: 28px;
}
.form-kicker {
  color: var(--ink-400);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}
.form-heading h2 {
  margin: 10px 0 6px;
  color: var(--ink-950);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.form-heading p {
  margin: 0;
  color: var(--ink-500);
  font-size: 13px;
}
.login-form-card :deep(.el-form-item) {
  margin-bottom: 18px;
}
.login-form-card label {
  display: block;
  margin-bottom: 7px;
  color: var(--ink-700);
  font-size: 12px;
  font-weight: 500;
}
.login-form-card :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: var(--radius-control);
  box-shadow: 0 0 0 1px var(--line) inset !important;
  background: #fff;
  transition: box-shadow 0.15s;
}
.login-form-card :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--blue-600) inset !important;
}
.login-form-card :deep(.el-input__prefix) {
  color: var(--ink-400);
}
.submit-button {
  width: 100%;
  height: 44px;
  margin-top: 4px;
  border: 0;
  border-radius: var(--radius-control);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  background: var(--primary);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.submit-button:hover {
  background: var(--primary-hover);
}
.submit-button:disabled {
  opacity: 0.5;
  cursor: wait;
}
.login-note {
  display: flex;
  justify-content: space-between;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--ink-400);
  font-size: 11px;
}
.login-note span {
  display: flex;
  align-items: center;
  gap: 5px;
}
.note-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--green-500);
}
.form-footer {
  position: absolute;
  bottom: 24px;
  color: var(--ink-400);
  font-size: 11px;
}
.form-footer span {
  margin-left: 10px;
  color: var(--ink-400);
  opacity: 0.7;
}

@media (max-width: 820px) {
  .login-page {
    grid-template-columns: 1fr;
  }
  .login-brand {
    min-height: auto;
    padding: 28px;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  .brand-body {
    margin: 32px 0 8px;
  }
  .brand-body h1 {
    font-size: 28px;
  }
  .brand-features,
  .brand-footer {
    display: none;
  }
  .login-form-side {
    min-height: calc(100vh - 200px);
    padding: 32px 28px 60px;
  }
}
</style>
