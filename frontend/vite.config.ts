import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../scMM/api/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/plotly.js-strict-dist-min/')) return 'plotly'
          if (/\/node_modules\/(?:vue(?:-router)?|@vue\/|pinia)\b/.test(id)) return 'vue'
          if (/\/node_modules\/(?:markdown-it|dompurify)\//.test(id)) return 'markdown'
        },
      },
    },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:5007' } },
})
