import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8077'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    proxy: {
      // Frontend calls same-origin /api; Vite proxies to the FastAPI dev server.
      '/api': { target: apiProxyTarget, changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
    },
  },
})
