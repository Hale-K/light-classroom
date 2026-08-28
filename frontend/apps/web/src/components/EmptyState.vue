<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  icon?: string
  title?: string
  desc?: string
  height?: number | string
  actionText?: string
}>()

const emit = defineEmits<{ (e: 'action'): void }>()
</script>

<template>
  <div class="empty" :style="{ height: typeof height === 'number' ? `${height}px` : height }">
    <div class="empty-icon"><Icon :name="icon || 'file-text'" :size="38" /></div>
    <div class="empty-title">{{ title || '暂无数据' }}</div>
    <div v-if="desc" class="empty-desc">{{ desc }}</div>
    <el-button v-if="actionText" class="empty-btn" plain type="primary" @click="emit('action')">
      {{ actionText }}
    </el-button>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
}
.empty-icon {
  width: 68px;
  height: 68px;
  border-radius: 16px;
  background: var(--blue-100);
  color: var(--blue-600);
  display: grid;
  place-items: center;
}
.empty-title { font-size: 15px; font-weight: 600; color: var(--ink-950); }
.empty-desc { font-size: 13px; color: var(--ink-500); }
.empty-btn { margin-top: 4px; }
</style>