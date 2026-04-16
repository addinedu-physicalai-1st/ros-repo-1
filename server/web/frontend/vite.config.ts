import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'

export default defineConfig({
  base: '/static/',
  plugins: [
    react(),
    tailwindcss(),
  ],
  build: {
    outDir: '../static',
    emptyOutDir: false,
    rollupOptions: {
      input: {
        table_ui: resolve(__dirname, 'table_ui/index.html'),
        kitchen:  resolve(__dirname, 'kitchen/index.html'),
        staff:    resolve(__dirname, 'staff/index.html'),
        kiosk:    resolve(__dirname, 'kiosk/index.html'),
      },
    },
  },
})
