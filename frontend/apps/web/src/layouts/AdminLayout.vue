<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import Icon from '@/components/Icon.vue'
import { useAdminStore } from '@/stores/admin'

const route = useRoute()
const router = useRouter()
const admin = useAdminStore()

const activeItem = () => route.path

async function onLogout() {
  await ElMessageBox.confirm('确定退出平台管理后台吗？', '退出登录', {
    confirmButtonText: '退出',
    cancelButtonText: '取消',
    type: 'warning',
  })
  admin.logout()
  router.replace('/admin/login')
}
</script>

<template>
  <el-container class="admin-root">
    <el-aside width="224px" class="admin-aside">
      <div class="brand">
        <div class="brand-mark">管</div>
        <div class="brand-text">
          <div class="brand-name">智衡 · 平台管理</div>
          <div class="brand-en">ZhiHeng Platform</div>
        </div>
      </div>
      <nav class="nav">
        <router-link to="/admin/schools" class="nav-item" :class="{ active: activeItem() === '/admin/schools' }">
          <Icon name="users" :size="18" class="nav-icon" />
          <span class="nav-label">学校管理</span>
        </router-link>
      </nav>
    </el-aside>

    <el-container>
      <el-header height="56px" class="admin-header">
        <div class="header-title">{{ route.meta.title || '平台管理' }}</div>
        <div class="header-right">
          <span class="admin-name">超管 · {{ admin.admin?.name || admin.admin?.username }}</span>
          <el-dropdown trigger="click">
            <button class="icon-btn" type="button"><Icon name="settings" :size="17" /></button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="admin.logout(); router.replace('/admin/login')">
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="admin-main">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.admin-root {
  height: 100%;
}
.admin-aside {
  background: var(--surface-1);
  color: var(--ink-700);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--line);
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.brand-mark {
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--primary);
  color: #fff;
  font-weight: 700;
  display: grid;
  place-items: center;
  font-size: 14px;
}
.brand-text {
  line-height: 1.2;
}
.brand-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--ink-950);
  letter-spacing: 0.3px;
}
.brand-en {
  font-size: 10px;
  color: var(--ink-400);
  margin-top: 1px;
}
.nav {
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 38px;
  padding: 0 12px;
  border-radius: var(--radius-control);
  color: var(--ink-500);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover {
  background: var(--surface-2);
  color: var(--ink-950);
}
.nav-item.active {
  background: var(--primary-light);
  color: var(--primary);
  font-weight: 600;
}
.nav-item.active .nav-icon {
  color: var(--primary);
}
.nav-icon {
  flex-shrink: 0;
}
.nav-label {
  flex: 1;
}

.admin-header {
  background: var(--surface-1);
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}
.header-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-950);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.admin-name {
  font-size: 12px;
  color: var(--ink-400);
}
.icon-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: var(--radius-control);
  display: grid;
  place-items: center;
  color: var(--ink-500);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.icon-btn:hover {
  background: var(--surface-2);
  color: var(--ink-950);
}
.admin-main {
  padding: 0;
  background: var(--surface-0);
  overflow: auto;
}
</style>
