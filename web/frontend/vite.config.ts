// Nombre de archivo: vite.config.ts
// Ubicación de archivo: web/frontend/vite.config.ts
// Descripción: Configuración de Vite — entry único (index.html → src/main.ts) para SPA unificado

import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';

// El CSS de Phosphor declara woff2, woff, ttf y svg; Vite emite los cuatro a dist/ (~3,5 MB) aunque
// todo navegador soportado baja sólo el woff2. Se deja únicamente esa URL en el @font-face.
function phosphorSoloWoff2(): Plugin {
  return {
    name: 'phosphor-solo-woff2',
    enforce: 'pre',
    transform(code, id) {
      if (!/@phosphor-icons[\\/]web[\\/]src[\\/][a-z]+[\\/]style\.css$/.test(id)) return null;
      const salida = code.replace(/(url\("[^"]+\.woff2"\) format\("woff2"\)),[^;]*;/, '$1;');
      if (salida === code) throw new Error(`phosphor-solo-woff2: no se encontró el @font-face en ${id}`);
      return { code: salida, map: null };
    },
  };
}

export default defineConfig({
  plugins: [phosphorSoloWoff2(), vue()],
  build: {
    outDir: 'dist',
  },
  // El worker de MapLibre (FO Monitor) es un módulo ES con imports a un chunk compartido.
  worker: {
    format: 'es',
  },
});
