import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    // Sólo para `npm run dev`: en producción el dashboard y el API viven en
    // la misma imagen (StaticFiles montado detrás de las rutas del API,
    // §0/§4.1 del briefing), así que esto no hace falta ahí.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
