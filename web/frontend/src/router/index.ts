// Nombre de archivo: index.ts
// Ubicación de archivo: web/frontend/src/router/index.ts
// Descripción: Router unificado del SPA — rutas de panel, admin, login y SLA con guards de sesión

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useSession } from '../composables/useSession';

// Views
import LoginView from '../views/LoginView.vue';
import PanelLayout from '../components/PanelLayout.vue';
import PanelView from '../views/PanelView.vue';
import SlaView from '../views/SlaView.vue';
import ReportsHistoryView from '../views/ReportsHistoryView.vue';

// Admin
import AdminLayout from '../admin/components/AdminLayout.vue';
import AdminDashboard from '../admin/views/AdminDashboard.vue';
import AdminUsuarios from '../admin/views/AdminUsuarios.vue';
import AdminServicios from '../admin/views/AdminServicios.vue';
import AdminBaneos from '../admin/views/AdminBaneos.vue';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: LoginView,
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: PanelLayout,
    meta: { requiresAuth: true },
    children: [
      { path: '', component: PanelView },
      { path: 'sla', component: SlaView },
      { path: 'reports-history', component: ReportsHistoryView },
    ],
  },
  {
    path: '/admin',
    component: AdminLayout,
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      { path: '', component: AdminDashboard },
      { path: 'usuarios', component: AdminUsuarios },
      { path: 'servicios', component: AdminServicios },
      { path: 'Servicios/Baneos', component: AdminBaneos },
      { path: ':pathMatch(.*)*', redirect: '/admin' },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  // Rutas públicas
  if (to.meta.requiresAuth === false) return true;

  const { ensureSession, state } = useSession();
  await ensureSession();

  if (!state.value.authenticated) {
    return '/login';
  }

  if (to.meta.requiresAdmin && (state.value.role ?? '').toLowerCase() !== 'admin') {
    return '/';
  }

  return true;
});

export default router;
