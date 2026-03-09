import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:9000'

export default defineConfig({
  plugins: [react()],
  base: '/viz/',
  server: {
    port: 3000,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/proxy/registry': {
        target: 'https://registry.devpunks.io',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/proxy\/registry/, ''),
      },
      '/proxy/global': {
        target: 'https://a2aregistry.org',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/proxy\/global/, ''),
      },
    },
  },
})
