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
        // 排课 SSE 可能跑数分钟，避免代理过早断开
        timeout: 0,
        proxyTimeout: 0,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const contentType = String(proxyRes.headers['content-type'] || '')
            if (!contentType.includes('text/event-stream')) return
            res.setHeader('Cache-Control', 'no-cache, no-transform')
            res.setHeader('X-Accel-Buffering', 'no')
            // 关闭可能把 SSE 攒包的压缩/转换
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            delete proxyRes.headers['content-encoding']
          })
        },
      },
    },
  },
})
