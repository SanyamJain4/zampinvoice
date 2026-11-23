import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath } from 'node:url'

const api = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // keep symlinked/junctioned source dirs on their given (short) path: avoids Windows MAX_PATH problems
  resolve: { preserveSymlinks: true, alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    // The SSE endpoint needs an un-buffered proxy; /api is forwarded as-is.
    proxy: { '/api': { target: api, changeOrigin: true } },
  },
  preview: { port: 5173, proxy: { '/api': { target: api, changeOrigin: true } } },
  test: { environment: 'jsdom', globals: true, css: false, include: ['src/**/*.test.{ts,tsx}'] },
})
