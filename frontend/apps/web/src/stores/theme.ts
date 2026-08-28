import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

export type ThemeKey =
  | 'business'
  | 'minimal'
  | 'classic'
  | 'dark'
  | 'cute'
  | 'anime'
  | 'mature'

export interface ThemeOption {
  key: ThemeKey
  label: string
  desc: string
  swatch: string[]
  group: '商务风' | '个性风'
}

export const THEMES: ThemeOption[] = [
  // 商务风
  {
    key: 'business',
    label: '企业商务',
    desc: '深蓝主色 · 正式专业',
    swatch: ['#1D4ED8', '#F5F7FA', '#FFFFFF'],
    group: '商务风',
  },
  {
    key: 'mature',
    label: '成熟稳重',
    desc: '深灰蓝 · 年长教师首选',
    swatch: ['#1E3A5F', '#F5F5F4', '#FFFFFF'],
    group: '商务风',
  },
  {
    key: 'minimal',
    label: '简约近黑',
    desc: '近黑主色 · 极简克制',
    swatch: ['#111827', '#FAFAFA', '#FFFFFF'],
    group: '商务风',
  },
  {
    key: 'classic',
    label: '经典蓝橙',
    desc: '亮蓝+橙 · 原始风格',
    swatch: ['#1677E8', '#FF684D', '#F6F8FC'],
    group: '商务风',
  },
  // 个性风
  {
    key: 'cute',
    label: '可爱甜心',
    desc: '粉色马卡龙 · 年轻女老师',
    swatch: ['#EC4899', '#FDF2F8', '#FCE7F3'],
    group: '个性风',
  },
  {
    key: 'anime',
    label: '动漫热血',
    desc: '橙红活力 · 年轻男老师',
    swatch: ['#F97316', '#FFF7ED', '#FFEDD5'],
    group: '个性风',
  },
  {
    key: 'dark',
    label: '深色模式',
    desc: '暗色背景 · 护眼模式',
    swatch: ['#3B82F6', '#0F172A', '#1E293B'],
    group: '个性风',
  },
]

const STORAGE_KEY = 'zhiheng-theme'

export const useThemeStore = defineStore('theme', () => {
  const saved = (localStorage.getItem(STORAGE_KEY) as ThemeKey) || 'business'
  const current = ref<ThemeKey>(saved)

  const currentOption = computed(() => THEMES.find((t) => t.key === current.value)!)

  function apply(theme: ThemeKey) {
    current.value = theme
    if (theme === 'business') {
      document.documentElement.removeAttribute('data-theme')
    } else {
      document.documentElement.setAttribute('data-theme', theme)
    }
    localStorage.setItem(STORAGE_KEY, theme)
  }

  function init() {
    apply(current.value)
  }

  function cycle() {
    const idx = THEMES.findIndex((t) => t.key === current.value)
    const next = THEMES[(idx + 1) % THEMES.length]
    apply(next.key)
  }

  watch(current, (val) => {
    window.dispatchEvent(new CustomEvent('theme-change', { detail: { theme: val } }))
  })

  return { current, currentOption, THEMES, apply, init, cycle }
})
