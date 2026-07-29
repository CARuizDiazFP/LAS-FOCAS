// Nombre de archivo: index.ts
// Ubicación de archivo: web/frontend/src/router/index.ts
// Descripción: Router unificado del SPA — rutas de panel, admin, login y SLA con guards de sesión

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useSession } from '../composables/useSession';

const LoginView = () => import('../views/LoginView.vue');
const AppShell = () => import('../components/app-shell/AppShell.vue');
const PanelView = () => import('../views/PanelView.vue');
const SlaView = () => import('../views/SlaView.vue');
const ReportsHistoryView = () => import('../views/ReportsHistoryView.vue');
const ServiciosView = () => import('../views/ServiciosView.vue');
const ServicioDetalleView = () => import('../views/ServicioDetalleView.vue');
const CamaraDetailView = () => import('../views/CamaraDetailView.vue');
const RepetitividadTab = () => import('../views/tabs/RepetitividadTab.vue');
const VlanTab = () => import('../views/tabs/VlanTab.vue');
const FoTab = () => import('../views/tabs/FoTab.vue');
const CienaTab = () => import('../views/tabs/CienaTab.vue');
const InfraTab = () => import('../views/tabs/InfraTab.vue');
const AdminDashboard = () => import('../admin/views/AdminDashboard.vue');
const AdminUsuarios = () => import('../admin/views/AdminUsuarios.vue');
const AdminServicios = () => import('../admin/views/AdminServicios.vue');
const AdminIngesta = () => import('../admin/views/AdminIngesta.vue');
const AdminIngestaServicios = () => import('../admin/views/AdminIngestaServicios.vue');
const AdminIngestaCamaras = () => import('../admin/views/AdminIngestaCamaras.vue');
const AdminBaneos = () => import('../admin/views/AdminBaneos.vue');

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'panel',
        component: PanelView,
        meta: {
          navLabel: 'Panel',
          navDescription: 'Home del panel con chat principal.',
          navOrder: 10,
          navSection: 'Operación',
        },
      },
      {
        path: 'infra',
        name: 'infra',
        component: InfraTab,
        meta: {
          navLabel: 'Infraestructura FO',
          navDescription: 'Dashboard operativo de cámaras y servicios FO.',
          navOrder: 15,
          navSection: 'Operación',
        },
      },
      {
        path: 'repetitividad',
        name: 'repetitividad',
        component: RepetitividadTab,
        meta: {
          navLabel: 'Repetitividad',
          navDescription: 'Generación del informe de repetitividad.',
          navOrder: 16,
          navSection: 'Operación',
        },
      },
      {
        path: 'toolkit/vlan',
        name: 'toolkit-vlan',
        component: VlanTab,
        meta: {
          navLabel: 'Comparador VLAN',
          navDescription: 'Comparación de configuraciones VLAN.',
          navOrder: 17,
          navSection: 'Operación',
        },
      },
      {
        path: 'fo',
        name: 'fo',
        component: FoTab,
        meta: {
          navLabel: 'FO',
          navDescription: 'Comparador FO.',
          navOrder: 18,
          navSection: 'Operación',
        },
      },
      {
        path: 'dwdm/ciena',
        name: 'dwdm-ciena',
        component: CienaTab,
        meta: {
          navLabel: 'Alarmas Ciena',
          navDescription: 'Procesamiento de alarmas DWDM Ciena.',
          navOrder: 19,
          navSection: 'Operación',
        },
      },
      {
        path: 'sla',
        name: 'sla',
        component: SlaView,
        meta: {
          navLabel: 'SLA',
          navDescription: 'Generación de informes SLA sobre Excel o base.',
          navOrder: 20,
          navSection: 'Operación',
        },
      },
      {
        path: 'reports-history',
        name: 'reports-history',
        component: ReportsHistoryView,
        meta: {
          navLabel: 'Reportes',
          navDescription: 'Historial de artefactos generados por el panel.',
          navOrder: 30,
          navSection: 'Operación',
        },
      },
      {
        path: 'servicios',
        name: 'servicios',
        component: ServiciosView,
        meta: {
          navLabel: 'Servicios',
          navDescription: 'Visor operativo con búsqueda y scroll infinito.',
          navOrder: 31,
          navSection: 'Operación',
        },
      },
      {
        path: 'servicios/ID/:idServicio',
        name: 'servicios-detail',
        component: ServicioDetalleView,
      },
      { path: 'infra/Camaras/:id(\\d+)', name: 'camara-detail', component: CamaraDetailView },
    ],
  },
  {
    path: '/admin',
    component: AppShell,
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: '',
        name: 'admin-dashboard',
        component: AdminDashboard,
        meta: {
          requiresAdmin: true,
          navLabel: 'Admin',
          navDescription: 'Acceso al dashboard administrativo.',
          navOrder: 100,
          navSection: 'Administración',
        },
      },
      {
        path: 'usuarios',
        name: 'admin-usuarios',
        component: AdminUsuarios,
        meta: {
          requiresAdmin: true,
          navLabel: 'Usuarios',
          navDescription: 'Gestión de usuarios y contraseñas.',
          navOrder: 110,
          navSection: 'Administración',
        },
      },
      {
        path: 'servicios',
        name: 'admin-servicios',
        component: AdminServicios,
        meta: {
          requiresAdmin: true,
          navLabel: 'Servicios',
          navDescription: 'Configuración operativa y controles auxiliares.',
          navOrder: 120,
          navSection: 'Administración',
        },
      },
      {
        path: 'Servicios/Baneos',
        name: 'admin-baneos',
        component: AdminBaneos,
        meta: {
          requiresAdmin: true,
          navLabel: 'Baneos',
          navDescription: 'Controles y monitoreo del servicio de baneos.',
          navOrder: 130,
          navSection: 'Administración',
        },
      },
      {
        path: 'ingesta',
        name: 'admin-ingesta',
        component: AdminIngesta,
        meta: {
          requiresAdmin: true,
          navLabel: 'Ingesta',
          navDescription: 'Ingesta de excel para servicios SLA.',
          navOrder: 140,
          navSection: 'Administración',
        },
      },
      {
        path: 'ingesta/servicios',
        name: 'admin-ingesta-servicios',
        component: AdminIngestaServicios,
        meta: { requiresAdmin: true },
      },
      {
        path: 'ingesta/camaras',
        name: 'admin-ingesta-camaras',
        component: AdminIngestaCamaras,
        meta: { requiresAdmin: true },
      },
      { path: ':pathMatch(.*)*', redirect: '/admin' },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

const legacyTabRedirects: Record<string, string> = {
  infra: '/infra',
  rep: '/repetitividad',
  repetitividad: '/repetitividad',
  vlan: '/toolkit/vlan',
  fo: '/fo',
  ciena: '/dwdm/ciena',
};

router.beforeEach(async (to) => {
  if (to.path === '/' && typeof to.query.tab === 'string') {
    const legacyTab = to.query.tab.toLowerCase();
    const redirectPath = legacyTabRedirects[legacyTab];

    if (redirectPath) {
      const nextQuery = { ...to.query };
      delete nextQuery.tab;
      return { path: redirectPath, query: nextQuery };
    }
  }

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
