// Nombre de archivo: vite.config.ts
// Ubicación de archivo: web/frontend/vite.config.ts
// Descripción: Configuración de Vite — dual entry point: chat client (main.js) y admin SPA (admin.js)

import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: 'src/chat/main.ts',
        admin: 'src/admin/main.ts',
      },
      output: {
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/chunk-[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
  },
});
