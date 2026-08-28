<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAdminStore } from '@/stores/admin'
import { APP_NAME, APP_NAME_EN } from '@zhiheng/shared'

const router = useRouter()
const route = useRoute()
const admin = useAdminStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    await admin.login(username.value, password.value)
    const redirect = (route.query.redirect as string) || '/admin/schools'
    router.replace(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="admin-login">
    <div class="card">
      <div class="brand">
        <div class="brand-mark">管</div>
        <div>
          <div class="title">平台管理后台</div>
          <div class="sub">{{ APP_NAME }} {{ APP_NAME_EN }} · 学校开通与运营</div>
        </div>
      </div>

      <el-form @submit.prevent="onLogin">
        <el-form-item>
          <el-input v-model="username" placeholder="管理员账号" size="large">
            <template #prefix><span style="color: var(--ink-400); font-size: 12px;">账号</span></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" show-password placeholder="登录密码" size="large" @keyup.enter="onLogin" />
        </el-form-item>
        <el-button type="primary" size="large" class="submit" :loading="loading" @click="onLogin">
          登 录
        </el-button>
      </el-form>

      <div class="hint">进入学校端请前往「学校登录」</div>
    </div>
  </div>
</template>

<style scoped>
.admin-login {
  height: 100%;
  display: grid;
  place-items: center;
  background: var(--surface-0);
}
.card {
  width: 380px;
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 32px 28px 24px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}
.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 9px;
  background: var(--primary);
  color: #fff;
  font-size: 18px;
  font-weight: 700;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.title {
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-950);
}
.sub {
  font-size: 12px;
  color: var(--ink-400);
  margin-top: 2px;
}
.submit {
  width: 100%;
  margin-top: 4px;
  border-radius: var(--radius-control);
  height: 42px;
  font-weight: 600;
}
.hint {
  margin-top: 18px;
  text-align: center;
  font-size: 12px;
  color: var(--ink-400);
}
</style>
