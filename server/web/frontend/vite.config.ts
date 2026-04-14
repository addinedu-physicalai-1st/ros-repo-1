import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: '/static/table_ui/',
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    outDir: '../static/table_ui',
    emptyOutDir: true,
  },
})
