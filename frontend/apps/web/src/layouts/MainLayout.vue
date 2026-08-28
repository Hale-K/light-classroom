<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import Icon from '@/components/Icon.vue'
import Pet from '@/components/Pet.vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { authApi } from '@zhiheng/api'
import { APP_NAME } from '@zhiheng/shared'
import type { MenuNode } from '@zhiheng/shared'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const themeStore = useThemeStore()

// 主题分组
const themeGroups = computed(() => {
  const groups: Record<string, typeof themeStore.THEMES> = {}
  for (const t of themeStore.THEMES) {
    if (!groups[t.group]) groups[t.group] = []
    groups[t.group].push(t)
  }
  return groups
})
const menus = ref<MenuNode[]>([])
const petFloat = ref<HTMLElement>()
const petRef = ref<InstanceType<typeof Pet>>()
const petPosition = reactive({ x: 0, y: 0 })
let petDrag: {
  pointerId: number; startX: number; startY: number; originX: number; originY: number; moved: boolean
} | null = null
let suppressPetClick = false
const isFullscreen = computed(() => route.meta.fullscreen === true)
const academicTerm = computed(() => {
  const now = new Date()
  const year = now.getFullYear()
  const month = now.getMonth() + 1
  const startYear = month >= 8 ? year : year - 1
  const term = month >= 2 && month < 8 ? 2 : 1
  return `${startYear}—${startYear + 1} 学年 · 第 ${term} 学期`
})

async function loadMenus() {
  try {
    const res = await authApi.menus()
    menus.value = res.menus
  } catch {
    menus.value = []
  }
}

function clampPetPosition(x: number, y: number) {
  const width = petFloat.value?.offsetWidth || 170
  const height = petFloat.value?.offsetHeight || 140
  petPosition.x = Math.min(Math.max(8, x), Math.max(8, window.innerWidth - width - 8))
  petPosition.y = Math.min(Math.max(8, y), Math.max(8, window.innerHeight - height - 8))
}

function restorePetPosition() {
  try {
    const saved = JSON.parse(localStorage.getItem('zh_pet_position') || 'null') as { x: number; y: number } | null
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      clampPetPosition(saved.x, saved.y)
      return
    }
  } catch { /* 使用默认右下角位置 */ }
  clampPetPosition(window.innerWidth - 194, window.innerHeight - 164)
}

function onPetPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  petRef.value?.setDragging(true)
  petDrag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: petPosition.x,
    originY: petPosition.y,
    moved: false,
  }
  petFloat.value?.setPointerCapture(event.pointerId)
}

function onPetPointerMove(event: PointerEvent) {
  if (!petDrag || petDrag.pointerId !== event.pointerId) return
  const deltaX = event.clientX - petDrag.startX
  const deltaY = event.clientY - petDrag.startY
  petDrag.moved ||= Math.hypot(deltaX, deltaY) > 4
  if (petDrag.moved) clampPetPosition(petDrag.originX + deltaX, petDrag.originY + deltaY)
}

function onPetPointerUp(event: PointerEvent) {
  if (!petDrag || petDrag.pointerId !== event.pointerId) return
  suppressPetClick = petDrag.moved
  petFloat.value?.releasePointerCapture(event.pointerId)
  petDrag = null
  petRef.value?.setDragging(false)
  localStorage.setItem('zh_pet_position', JSON.stringify(petPosition))
}

function onPetClickCapture(event: MouseEvent) {
  if (!suppressPetClick) return
  event.preventDefault()
  event.stopPropagation()
  suppressPetClick = false
}

function keepPetInViewport() {
  clampPetPosition(petPosition.x, petPosition.y)
}

onMounted(() => {
  loadMenus()
  restorePetPosition()
  window.addEventListener('resize', keepPetInViewport)
})
onBeforeUnmount(() => window.removeEventListener('resize', keepPetInViewport))

// 路由切换时宠物挥手
watch(() => route.path, (newPath, oldPath) => {
  if (newPath !== oldPath) {
    window.dispatchEvent(new CustomEvent('pet:act', { detail: { action: 'wave', duration: 2000 } }))
  }
})
const activeMenu = computed(() => route.path)
const currentTitle = computed(() => String(route.meta.title || '工作台'))
const roleLabel = computed(() => {
  if (auth.user?.role === 'director') return '校长管理员'
  if (auth.user?.roles?.includes('academic_director')) return '教导主任'
  if (auth.user?.roles?.includes('head_teacher')) return '班主任'
  return '任教老师'
})

async function onLogout() {
  await ElMessageBox.confirm('确定退出当前工作台吗？', '退出登录', {
    confirmButtonText: '退出工作台',
    cancelButtonText: '继续使用',
    type: 'warning',
  })
  auth.logout()
  router.replace('/login')
}

function go(path?: string | null, available = true) {
  if (path && available) router.push(path)
}

</script>

<template>
  <el-container class="layout-root" :class="{ 'layout-root--fullscreen': isFullscreen }">
    <el-aside v-if="!isFullscreen" width="240px" class="layout-aside">
      <div class="brand">
        <div class="brand-mark"><span>衡</span></div>
        <div class="brand-copy">
          <div class="brand-name">{{ APP_NAME }}</div>
          <div class="brand-en">轻课堂教务系统</div>
        </div>
      </div>

      <div class="workspace-switcher">
        <div class="workspace-info">
          <div class="workspace-label">当前学校</div>
          <div class="workspace-value">{{ auth.schoolCode }}</div>
        </div>
        <Icon name="chevron-down" :size="14" class="workspace-chevron" />
      </div>

      <el-scrollbar class="menu-scroll">
        <nav class="nav" aria-label="主导航">
          <section v-for="group in menus" :key="group.key" class="nav-group" :aria-labelledby="`menu-${group.key}`">
            <h2 :id="`menu-${group.key}`" class="nav-caption">
              {{ group.title }}
            </h2>
            <button
              v-for="item in group.children || []"
              :key="item.key"
              type="button"
              class="nav-item"
              :class="{ active: item.path && activeMenu.startsWith(item.path) }"
              @click="go(item.path)"
            >
              <span class="nav-icon-wrap"><Icon :name="item.icon" :size="17" /></span>
              <span class="nav-label">{{ item.title }}</span>
            </button>
          </section>
        </nav>
      </el-scrollbar>

      <div class="aside-bottom">
        <div class="aside-footer">
          <span class="footer-status"><span class="status-dot" />服务正常</span>
          <span class="footer-version">Web 1.0</span>
        </div>
      </div>
    </el-aside>

    <el-container class="layout-content" :class="{ 'layout-content--fullscreen': isFullscreen }">
      <el-header v-if="!isFullscreen" height="60px" class="layout-header">
        <div class="header-left">
          <div class="breadcrumb"><span>轻课堂</span><span class="breadcrumb-sep">/</span><strong>{{ currentTitle }}</strong></div>
          <span class="header-context">{{ academicTerm }}</span>
        </div>
        <div class="header-right">
          <el-dropdown trigger="click" @command="(k: string) => themeStore.apply(k as any)">
            <button type="button" class="theme-switch" :title="`当前：${themeStore.currentOption.label}`">
              <span class="theme-dot" :style="{ background: themeStore.currentOption.swatch[0] }" />
              <span class="theme-label">{{ themeStore.currentOption.label }}</span>
              <Icon name="chevron-down" :size="13" />
            </button>
            <template #dropdown>
              <el-dropdown-menu class="theme-menu">
                <template v-for="(items, group) in themeGroups" :key="group">
                  <div class="theme-group-title">{{ group }}</div>
                  <el-dropdown-item
                    v-for="t in items"
                    :key="t.key"
                    :command="t.key"
                    :class="{ 'theme-item-active': t.key === themeStore.current }"
                  >
                    <span class="theme-swatch">
                      <i v-for="(c, i) in t.swatch" :key="i" :style="{ background: c }" />
                    </span>
                    <span class="theme-item-copy">
                      <strong>{{ t.label }}</strong>
                      <small>{{ t.desc }}</small>
                    </span>
                    <Icon v-if="t.key === themeStore.current" name="circle-check" :size="15" class="theme-check" />
                  </el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown trigger="click">
            <button type="button" class="account">
              <span class="avatar">{{ (auth.displayName || '师')[0] }}</span>
              <span class="account-copy"><strong>{{ auth.displayName || '未登录' }}</strong><small>{{ roleLabel }}</small></span>
              <Icon name="chevron-down" :size="14" class="account-chevron" />
            </button>
            <template #dropdown>
              <el-dropdown-menu><el-dropdown-item @click="onLogout">退出登录</el-dropdown-item></el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view v-slot="{ Component }"><component :is="Component" /></router-view>
      </el-main>
    </el-container>

    <div
      v-if="!isFullscreen"
      ref="petFloat"
      class="pet-float"
      :class="{ 'pet-float--dragging': petDrag }"
      :style="{ left: `${petPosition.x}px`, top: `${petPosition.y}px` }"
      aria-label="可拖拽桌面宠物"
      @pointerdown="onPetPointerDown"
      @pointermove="onPetPointerMove"
      @pointerup="onPetPointerUp"
      @pointercancel="onPetPointerUp"
      @click.capture="onPetClickCapture"
    >
      <Pet ref="petRef" />
    </div>
  </el-container>
</template>

<style scoped>
.layout-root {
  height: 100%;
  min-width: 1080px;
}
.layout-root--fullscreen {
  min-width: 0;
}

/* 浅色侧边栏 */
.layout-aside {
  background: var(--surface-1);
  color: var(--ink-700);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--line);
}

.brand {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  flex-shrink: 0;
}
.brand-mark {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  background: var(--primary);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  border-radius: 7px;
}
.brand-copy {
  line-height: 1.2;
}
.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-950);
  letter-spacing: 0.5px;
}
.brand-en {
  margin-top: 2px;
  color: var(--ink-400);
  font-size: 11px;
}

.workspace-switcher {
  margin: 14px 14px 10px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-0);
}
.workspace-info {
  min-width: 0;
}
.workspace-label {
  font-size: 10px;
  color: var(--ink-400);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.workspace-value {
  margin-top: 2px;
  color: var(--ink-950);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.workspace-chevron {
  color: var(--ink-400);
  flex-shrink: 0;
}

.menu-scroll {
  flex: 1;
}
.nav-caption {
  margin: 0;
  padding: 14px 10px 6px;
  color: var(--ink-400);
  font-size: 10px;
  letter-spacing: 1px;
  text-transform: uppercase;
  font-weight: 600;
}
.nav {
  padding: 0 10px;
}
.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-group + .nav-group {
  margin-top: 3px;
}
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 38px;
  padding: 0 10px;
  color: var(--ink-500);
  background: transparent;
  border: 0;
  border-radius: var(--radius-control);
  text-align: left;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.15s, color 0.15s;
}
.nav-item:hover {
  background: var(--surface-2);
  color: var(--ink-950);
}
.nav-item.active {
  color: var(--primary);
  background: var(--primary-light);
  font-weight: 600;
}
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: var(--primary);
}
.nav-item.active .nav-icon-wrap {
  color: var(--primary);
}
.nav-icon-wrap {
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  color: currentColor;
  flex-shrink: 0;
}
.nav-label {
  flex: 1;
  font-size: 13px;
}

.aside-bottom {
  padding: 12px 14px 14px;
  border-top: 1px solid var(--line);
}
.aside-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 4px;
}
.footer-status {
  color: var(--ink-400);
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green-500);
}
.footer-version {
  color: var(--ink-400);
  font-size: 10px;
}

.layout-content {
  min-width: 0;
}
.layout-content--fullscreen {
  width: 100%;
}

.layout-header {
  background: var(--surface-1);
  border-bottom: 1px solid var(--line);
  box-shadow: var(--shadow-xs);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
  position: relative;
  z-index: 1;
}
.header-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-400);
  font-size: 12px;
}
.breadcrumb-sep {
  color: var(--line);
  font-weight: 400;
}
.breadcrumb strong {
  color: var(--ink-950);
  font-size: 14px;
  font-weight: 600;
}
.header-context {
  font-size: 11px;
  color: var(--ink-400);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 主题切换器 */
.theme-switch {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--surface-1);
  color: var(--ink-700);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  transition: border-color 0.15s, background 0.15s;
}
.theme-switch:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.theme-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 1px solid rgba(0, 0, 0, 0.1);
  flex-shrink: 0;
}
.theme-label {
  font-weight: 500;
}
.theme-switch svg {
  color: var(--ink-400);
}
.theme-menu {
  width: 230px;
  padding: 8px !important;
}
.theme-group-title {
  padding: 8px 10px 4px;
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-400);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}
.theme-menu .el-dropdown-menu__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px !important;
  border-radius: 6px;
}
.theme-menu .el-dropdown-menu__item.theme-item-active {
  background: var(--primary-light);
}
.theme-swatch {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.theme-swatch i {
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid rgba(0, 0, 0, 0.08);
}
.theme-swatch i:first-child {
  border-radius: 3px 0 0 3px;
}
.theme-swatch i:last-child {
  border-radius: 0 3px 3px 0;
}
.theme-item-copy {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.theme-item-copy strong {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-950);
}
.theme-item-copy small {
  font-size: 10px;
  color: var(--ink-400);
}
.theme-check {
  color: var(--primary);
  flex-shrink: 0;
}
.account {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  padding: 4px 8px;
  border-radius: var(--radius-control);
  transition: background 0.15s;
}
.account:hover {
  background: var(--surface-2);
}
.avatar {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 7px;
  color: #fff;
  background: var(--primary);
  font-weight: 600;
  font-size: 13px;
}
.account-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.account-copy strong {
  color: var(--ink-950);
  font-size: 12px;
  font-weight: 600;
}
.account-copy small {
  color: var(--ink-400);
  font-size: 10px;
}
.account-chevron {
  color: var(--ink-400);
}

.layout-main {
  padding: 0;
  background: var(--surface-0);
  overflow: auto;
}

.pet-float {
  position: fixed;
  z-index: 20;
  width: 170px;
  cursor: grab;
  touch-action: none;
  user-select: none;
  will-change: left, top;
}
.pet-float--dragging {
  cursor: grabbing;
}

@media (max-width: 1180px) {
  .layout-root {
    min-width: 0;
  }
  .account-copy,
  .account-chevron {
    display: none;
  }
  .pet-float {
    transform: scale(0.84);
    transform-origin: right bottom;
  }
}
</style>
