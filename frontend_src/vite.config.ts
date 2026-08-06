import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const __dirname = new URL('.', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
      '/video_feed': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8002', ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: '../frontend',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
  },
})

