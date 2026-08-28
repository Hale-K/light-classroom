import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      '@zhiheng/api': fileURLToPath(new URL('../../packages/api/src', import.meta.url)),
      '@zhiheng/shared': fileURLToPath(new URL('../../packages/shared/src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 开发代理：/api/v1 -> 本地后端（FastAPI :8001）
      '/api/v1': {
        target: process.env.VITE_DEV_PROXY || 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})