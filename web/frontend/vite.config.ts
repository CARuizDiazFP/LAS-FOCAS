// Nombre de archivo: vite.config.ts
// Ubicación de archivo: web/frontend/vite.config.ts
// Descripción: Configuración de Vite para generar assets con nombres estables

import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        entryFileNames: 'assets/main.js',
        chunkFileNames: 'assets/chunk-[name].js',
        assetFileNames: 'assets/[name][extname]'
      }
    }
  }
});
