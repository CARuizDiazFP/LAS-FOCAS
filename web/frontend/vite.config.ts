// Nombre de archivo: vite.config.ts
// Ubicación de archivo: web/frontend/vite.config.ts
// Descripción: Configuración de Vite — entry único (index.html → src/main.ts) para SPA unificado

import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
  },
});
