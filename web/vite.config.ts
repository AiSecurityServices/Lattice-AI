import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 6317,
    proxy: {
      '/api': 'http://127.0.0.1:8742',
      '/health': 'http://127.0.0.1:8742',
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 主 chunk 762KB > 500KB；按依赖族拆分 vendor chunk：
        // markdown 栈（react-markdown/micromark/remark…）、DAG 画布栈
        // （@xyflow/dagre/d3）、react 家族与图标库各自独立加载。
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (
            id.includes('react-markdown') ||
            id.includes('remark-') ||
            id.includes('unified') ||
            id.includes('micromark') ||
            id.includes('mdast-') ||
            id.includes('unist-') ||
            id.includes('hast-') ||
            id.includes('vfile') ||
            id.includes('stringify')
          ) {
            return 'vendor-markdown'
          }
          if (
            id.includes('@xyflow') ||
            id.includes('@dagrejs') ||
            id.includes('dagre') ||
            id.includes('/d3-') ||
            id.includes('@d3')
          ) {
            return 'vendor-graph'
          }
          if (
            id.includes('/react/') ||
            id.includes('/react-dom/') ||
            id.includes('scheduler') ||
            id.includes('use-sync-external-store') ||
            id.includes('classcat')
          ) {
            return 'vendor-react'
          }
          if (id.includes('@phosphor-icons')) return 'vendor-icons'
          return 'vendor'
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    css: true,
    setupFiles: './src/test/setup.ts',
    exclude: ['tests/e2e/**', '**/node_modules/**', '**/dist/**'],
  },
})
