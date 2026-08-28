import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5176,
    proxy: {
      // 开发代理：/api/v1 -> 本地智衡后端（FastAPI :8001）
      '/api/v1': {
        target: process.env.VITE_DEV_PROXY || 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
