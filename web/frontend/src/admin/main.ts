// Nombre de archivo: main.ts
// Ubicación de archivo: web/frontend/src/admin/main.ts
// Descripción: Entry point del SPA admin Vue 3

import { createApp } from 'vue';
import App from './App.vue';
import router from './router/index';
import './admin.css';

createApp(App).use(router).mount('#admin-app');
