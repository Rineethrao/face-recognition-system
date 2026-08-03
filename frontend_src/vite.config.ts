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
      '/health': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/cameras': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/camera': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/persons': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/register': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/recognitions': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/recognition': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/detected_faces': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/faces': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/reports': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/history': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/candidates': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/attendance': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/security': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/retail': { target: 'http://127.0.0.1:8002', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8002', ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: '../frontend',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
  },
})

