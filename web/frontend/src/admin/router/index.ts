// Nombre de archivo: index.ts
// Ubicación de archivo: web/frontend/src/admin/router/index.ts
// Descripción: Vue Router del panel admin — rutas /admin* con guard de sesión admin

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import AdminDashboard from '../views/AdminDashboard.vue';
import AdminUsuarios from '../views/AdminUsuarios.vue';
import AdminServicios from '../views/AdminServicios.vue';
import AdminBaneos from '../views/AdminBaneos.vue';

const routes: RouteRecordRaw[] = [
  { path: '/admin',                  component: AdminDashboard },
  { path: '/admin/usuarios',         component: AdminUsuarios },
  { path: '/admin/servicios',        component: AdminServicios },
  { path: '/admin/Servicios/Baneos', component: AdminBaneos },
  // Redirige cualquier sub-ruta desconocida al dashboard
  { path: '/admin/:pathMatch(.*)*',  redirect: '/admin' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Navigation guard: verifica sesión admin antes de cada ruta
router.beforeEach(async () => {
  try {
    const res = await fetch('/api/admin/me', { credentials: 'include' });
    if (!res.ok) {
      window.location.href = '/login';
      return false;
    }
  } catch {
    window.location.href = '/login';
    return false;
  }
});

export default router;
