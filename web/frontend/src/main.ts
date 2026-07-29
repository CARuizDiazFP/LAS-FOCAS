// Nombre de archivo: main.ts
// Ubicación de archivo: web/frontend/src/main.ts
// Descripción: Punto de entrada unificado del SPA — monta App con router y estilos globales

import { createApp } from 'vue';
import App from './App.vue';
import router from './router/index';
import './assets/styles/tokens.css';
import './admin/admin.css';
import './panel.css';
import '@phosphor-icons/web/regular';
import '@phosphor-icons/web/fill';

createApp(App).use(router).mount('#app');
