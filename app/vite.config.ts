import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Orchestrator API target (for dev proxy)
const ORCH_TARGET = process.env.VITE_ORCH_TARGET || 'http://localhost:8000'
// Agent API target (direct to user's agent, or via orchestrator in prod)
const AGENT_TARGET = process.env.VITE_AGENT_TARGET || 'http://localhost:9000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 3003,
    proxy: {
      // Orchestrator API
      '/orch': {
        target: ORCH_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/orch/, ''),
      },
      // Agent API (for direct agent calls)
      '/agent': {
        target: AGENT_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agent/, ''),
      },
    },
  },
})
