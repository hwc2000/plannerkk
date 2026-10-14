import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        // Point a second dev server at another API (e.g. a throwaway DB) without touching this file.
        target: (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
