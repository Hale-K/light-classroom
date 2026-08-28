import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './styles/theme.css'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { useAdminStore } from './stores/admin'
import { useThemeStore } from './stores/theme'
import { setAuthResolver } from '@zhiheng/api'
import { DEFAULT_SCHOOL_CODE } from '@zhiheng/shared'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 初始化主题（从 localStorage 读取并应用）
useThemeStore(pinia).init()

// 归一化历史残留值（早期默认 'default' 与后端租户 'demo' 不一致）
const readSchoolCode = () => {
  const c = (localStorage.getItem('zh_school_code') || '').trim()
  return !c || c === 'default' ? DEFAULT_SCHOOL_CODE : c
}

// 让 API 层从 auth store 读取 token / 学校代码；401 时登出并回登录
setAuthResolver({
  getToken: () => localStorage.getItem('zh_token'),
  getAdminToken: () => localStorage.getItem('zh_admin_token'),
  getSchoolCode: readSchoolCode,
  onUnauthorized: () => {
    const path = window.location.pathname
    if (path.startsWith('/admin')) {
      const adminStore = useAdminStore()
      adminStore.logout()
      router.replace('/admin/login')
      return
    }
    const auth = useAuthStore()
    auth.logout()
    router.replace('/login')
  },
})

app.mount('#app')